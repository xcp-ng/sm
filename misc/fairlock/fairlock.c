#include "fairlock.h"

int64_t get_current_time (void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

// -----------------------------------------------------------------------------

static inline void server_add_client (struct ServerState *state, int sock) {
    assert(state->client_count < MAX_CLIENTS);

    struct Client *client = &state->clients[state->client_count];
    if (client_new(client, sock, state->next_ticket)) return;

    ++state->client_count;
    ++state->next_ticket;
    state->dirty = true;

    sd_pid_notify_with_fds(0, 0, "FDSTORE=1", &sock, 1);
}

static inline void server_remove_client (struct ServerState *state, int index) {
    struct Client *client = &state->clients[index];
    syslog(LOG_INFO, "%s released (%c)\n", state->lock_path, client->mode ? client->mode : '?');
    client_close(client->sock);

    if (client_has_lock(client)) {
        if (client->mode == 'W') {
            assert(state->has_writer);
            state->has_writer = false;
        } else {
            assert(state->reader_count);
            --state->reader_count;
        }
    }

    assert(state->client_count);
    --state->client_count;
    memmove(client, client + 1, (state->client_count - index) * sizeof *client);
    state->dirty = true;
}

// -----------------------------------------------------------------------------

static inline void server_handle_client_event (struct ServerState *state, int index) {
    struct Client *client = &state->clients[index];
    const enum ClientState previous_state = client->state;
    const bool keep_client = client->mode
        ? client_read_data(state, client)
        : client_read_mode(client);

    if (!keep_client)
        server_remove_client(state, index);
    else if (client->state != previous_state)
        state->dirty = true;
}

// -----------------------------------------------------------------------------

static inline void server_journal_error (struct ServerState *state, const char *path, const int error) {
    if (state->journal_failed)
        return;

    state->journal_failed = true;
    syslog(LOG_ERR, "%s cannot write journal %s: %s\n", state->lock_path, path, strerror(error));
}

// The locks must not be sent then if false, a restarted server would not know their owners.
static inline bool server_write_journal (struct ServerState *state) {
    if (!state->journal_path)
        return true;

    char tmp_path[PATH_MAX];
    if (snprintf(tmp_path, sizeof tmp_path, "%s.tmp", state->journal_path) >= (int)sizeof tmp_path) {
        server_journal_error(state, state->journal_path, ENAMETOOLONG);
        return false;
    }

    if (!journal_write(state, tmp_path)) {
        server_journal_error(state, tmp_path, errno);
        unlink(tmp_path);
        return false;
    }

    if (rename(tmp_path, state->journal_path) != 0) {
        server_journal_error(state, state->journal_path, errno);
        unlink(tmp_path);
        return false;
    }

    state->journal_failed = false;
    return true;
}

// -----------------------------------------------------------------------------

// Rebuild the queue from the fds given back by systemd and the journal.
// Returns false if no listening socket was passed.
static bool server_restore (struct ServerState *state, int fd_count) {
    FILE *journal = state->journal_path ? fopen(state->journal_path, "re") : NULL;
    const int64_t current_time = get_current_time();

    for (int fd = SD_LISTEN_FDS_START; fd < SD_LISTEN_FDS_START + fd_count; ++fd) {
        if (sd_is_socket_unix(fd, SOCK_STREAM, 1, NULL, 0) > 0) {
            if (state->server_sock < 0)
                state->server_sock = fd;
            else
                close(fd);
            continue;
        }

        if (sd_is_socket_unix(fd, SOCK_STREAM, 0, NULL, 0) <= 0) {
            close(fd);
            continue;
        }

        struct Client client = {
            .sock = fd,
            .accepted_at = current_time
        };
        struct stat st;

        const bool known = state->client_count < MAX_CLIENTS
        && journal && fstat(fd, &st) == 0
        && journal_find(journal, st.st_ino, &client);

        if (!known) {
            syslog(LOG_WARNING, "%s dropping stored connection without journal entry\n", state->lock_path);
            client_close(fd);
            continue;
        }

        client.inode = st.st_ino;
        client.pid = client_get_pid(fd);
        state->clients[state->client_count++] = client;
    }

    if (journal)
        fclose(journal);

    qsort(state->clients, state->client_count, sizeof *state->clients, client_compare_tickets);

    for (int i = 0; i < state->client_count; ++i) {
        const struct Client *client = &state->clients[i];
        if (client->ticket >= state->next_ticket)
            state->next_ticket = client->ticket + 1;

        if (client_has_lock(client)) {
            if (client->mode == 'W')
                state->has_writer = true;
            else
                ++state->reader_count;
        }
    }

    if (state->client_count) {
        syslog(
            LOG_INFO, "%s restored %d client(s): %d reader(s), %d writer\n",
            state->lock_path, state->client_count, state->reader_count, state->has_writer
        );
    }

    state->dirty = true;
    return state->server_sock >= 0;
}

// -----------------------------------------------------------------------------

static inline int server_bind (struct ServerState *state) {
    const size_t lock_path_length = strlen(state->lock_path);
    if (!lock_path_length) {
        fprintf(stderr, "socket path is empty\n");
        errno = EINVAL;
        return EINVAL;
    }

    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    if (lock_path_length >= sizeof addr.sun_path) {
        fprintf(stderr, "socket path too long (max %zu): `%s`\n", sizeof addr.sun_path - 1, state->lock_path);
        errno = ENAMETOOLONG;
        return ENAMETOOLONG;
    }
    memcpy(addr.sun_path, state->lock_path, lock_path_length);

    // Unlink the server socket just in case.
    unlink(state->lock_path);

    state->server_sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (state->server_sock < 0) {
        fprintf(stderr, "socket() failed for `%s`: `%s`\n", state->lock_path, strerror(errno));
        return errno;
    }
    if (bind(state->server_sock, (const struct sockaddr *)&addr, sizeof addr) < 0) {
        fprintf(stderr, "bind() failed on socket `%s`: `%s`\n", state->lock_path, strerror(errno));
        return errno;
    }
    if (listen(state->server_sock, 64) < 0) {
        fprintf(stderr, "listen(64) failed on socket `%s`: `%s`\n", state->lock_path, strerror(errno));
        return errno;
    }

    return 0;
}

// Returns false if the journal could not be written
static bool server_sync (struct ServerState *state) {
    if (!state->dirty)
        return true;

    if (!server_write_journal(state))
        return false;
    state->dirty = false;
    int queued_count = 0;
    for (int i = 0; i < state->client_count; ++i)
        queued_count += !client_has_lock(&state->clients[i]);

    sd_notifyf(
        0, "STATUS=%d reader(s), %d writer, %d waiting",
        state->reader_count, state->has_writer, queued_count
    );
    return true;
}

// -----------------------------------------------------------------------------

static int server_get_next_poll_timeout (const struct ServerState *state) {
    int64_t deadline = state->watchdog_interval ? state->watchdog_next_ping : -1;
    // Still dirty after a sync: the journal could not be written, retry soon.
    if (state->dirty) {
        const int64_t retry_deadline = get_current_time() + JOURNAL_RETRY_DELAY;
        if (deadline < 0 || retry_deadline < deadline)
            deadline = retry_deadline;
    }
    for (int i = 0; i < state->client_count; ++i) {
        const struct Client *client = &state->clients[i];
        if (client->mode)
            continue;

        const int64_t client_deadline = client->accepted_at + MODE_TIMEOUT;
        if (deadline < 0 || client_deadline < deadline)
            deadline = client_deadline;
    }

    if (deadline < 0)
        return -1;

    const int64_t remaining_time = deadline - get_current_time();
    return remaining_time > 0 ? (int)remaining_time : 0;
}

// Drop the clients that did not send their mode in time.
static void server_close_expired_clients (struct ServerState *state) {
    const int64_t current_time = get_current_time();
    for (int i = state->client_count - 1; i >= 0; --i) {
        const struct Client *client = &state->clients[i];
        if (!client->mode && current_time - client->accepted_at >= MODE_TIMEOUT) {
            syslog(LOG_WARNING, "%s no mode received within %d ms\n", state->lock_path, MODE_TIMEOUT);
            server_remove_client(state, i);
        }
    }
}

static void server_ping_watchdog (struct ServerState *state) {
    if (!state->watchdog_interval)
        return;

    const int64_t current_time = get_current_time();
    if (current_time < state->watchdog_next_ping)
        return;

    sd_notify(0, "WATCHDOG=1");
    state->watchdog_next_ping = current_time + state->watchdog_interval;
}

// -----------------------------------------------------------------------------

static void server_process_clients (struct ServerState *state) {
    // A writer holds the lock: nobody else can be updated.
    if (state->has_writer)
        return;

    for (int i = 0; i < state->client_count; ++i) {
        assert(!state->has_writer);

        struct Client *client = &state->clients[i];
        if (client_has_lock(client)) {
            assert(client->mode == 'R');
            continue;
        }

        // Mode not known yet: the head of the queue must wait for it.
        if (!client->mode)
            break;

        const bool exclusive_write = client->mode == 'W';
        if (exclusive_write) {
            if (state->reader_count)
                break; // We must have no readers to give exclusive lock.
            state->has_writer = true;
        } else {
            ++state->reader_count;
        }

        client->state = CLIENT_GRANTED;
        client->lock_sent = false;
        client->granted_at = get_current_time();
        state->dirty = true;
        syslog(LOG_INFO, "%s acquired (%c)\n", state->lock_path, client->mode);

        if (exclusive_write)
            break; // Can't give lock to another client.
    }
}

static void server_send_locks (struct ServerState *state) {
    for (int i = 0; i < state->client_count; ++i) {
        struct Client *client = &state->clients[i];
        if (client->state != CLIENT_GRANTED || client->lock_sent)
            continue;

        // Notify client. We don't care about the return code.
        // SIGPIPE is also ignored in case of connection closed.
        static const char lock_message[] = "LOCK";
        write(client->sock, lock_message, sizeof lock_message);
        client->lock_sent = true;
    }
}

// -----------------------------------------------------------------------------

int main (int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Syntax: %s <socket filename> [<journal filename>]\n", argv[0]);
        exit(1);
    }

    struct ServerState state = {
        .lock_path = argv[1],
        .journal_path = argc > 2 ? argv[2] : NULL,
        .server_sock = -1,
        .dirty = true // Report the initial (empty) status.
    };

    // We may write to a connection whose client already went away. So ignore SIGPIPE.
    signal(SIGPIPE, SIG_IGN);

    openlog("fairlock", LOG_CONS | LOG_PID | LOG_NDELAY, LOG_LOCAL2);

    const int fd_count = sd_listen_fds(1);
    if (!server_restore(&state, fd_count > 0 ? fd_count : 0)) {
        if (server_bind(&state))
            exit(1);
    }

    uint64_t watchdog_usec;
    if (sd_watchdog_enabled(1, &watchdog_usec) > 0) {
        // Ping twice per period, as recommended by sd_watchdog_enabled(3).
        state.watchdog_interval = (int64_t)(watchdog_usec / 2000);
        state.watchdog_next_ping = get_current_time();
    }

    sd_notify(0, "READY=1");

    // Clients restored as granted must get their "LOCK" again: it may have been lost by the previous instance.
    server_process_clients(&state);
    if (server_sync(&state))
        server_send_locks(&state);

    for (;;) {
        struct pollfd pfds[MAX_CLIENTS + 1];

        // 1. Wait for events.
        struct pollfd *server_pfd = pfds;

        server_pfd->fd = state.server_sock;
        // Use only `POLLIN` if the max client limit is not reached.
        // We must not add new client if we reached the max client count.
        server_pfd->events = state.client_count < MAX_CLIENTS ? POLLIN : 0;
        server_pfd->revents = 0;

        for (int i = 0; i < state.client_count; ++i) {
            struct pollfd *client_pfd = pfds + i + 1;
            client_pfd->fd = state.clients[i].sock;
            client_pfd->events = POLLIN;
            client_pfd->revents = 0;
        }

        if (poll(pfds, state.client_count + 1, server_get_next_poll_timeout(&state)) < 0) {
            if (errno == EINTR)
                continue;
            fprintf(stderr, "poll() failed on socket %s: %s\n", state.lock_path, strerror(errno));
            exit(1);
        }

        server_ping_watchdog(&state);

        // 2. Handle client socket events.
        // Note: `server_remove_client` can shift data, so we must process from end array to start.
        for (int i = state.client_count - 1; i >= 0; --i) {
            if ((pfds[i + 1].revents & (POLLIN | POLLHUP | POLLERR)))
                server_handle_client_event(&state, i);
        }

        // 3. Drop clients that never announced their mode.
        server_close_expired_clients(&state);

        // 4. Handle new client.
        if (server_pfd->revents & POLLIN) {
            const int fd = accept(state.server_sock, NULL, NULL);
            if (fd >= 0) {
                server_add_client(&state, fd);
            } else if (errno != EINTR) {
                syslog(LOG_ERR, "%s accept() failed: %s\n", state.lock_path, strerror(errno));
                // Avoid a busy loop in case of EMFILE, ENFILE, ENOBUFS, ENOMEM...
                usleep(10000);
            }
        }

        // 5. And process locks of course.
        server_process_clients(&state);

        // 6. Journal the new state before telling the clients they own the lock.
        if (server_sync(&state))
            server_send_locks(&state);
    }

    closelog();
}
