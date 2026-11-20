#include "fairlock.h"

#define JOURNAL_LINE_SIZE 256

// -----------------------------------------------------------------------------
// Journal: the queue state, rewritten atomically after each change.
// It is keyed by socket inode so it can be matched with the fds systemd gives
// back from its fd store after a crash/restart (fd names require systemd >= 227).
// Format:
//   server <server pid>
//   <inode> <ticket> <mode> <state> <pid> <queued at> <granted at>
// Times use CLOCK_MONOTONIC in milliseconds, 0 if unknown.
// -----------------------------------------------------------------------------

// State cannot be longer than 15 chars.
static const char *const client_state_names[] = { "asked", "queued", "granted", "owned" };

bool journal_write (const struct ServerState *state, const char *path) {
    FILE *file = fopen(path, "we");
    if (!file)
        return false;

    fprintf(file, "server %d\n", (int)getpid());
    for (int i = 0; i < state->client_count; ++i) {
        const struct Client *client = &state->clients[i];
        fprintf(
            file, "%ju %" PRIu64 " %c %s %d %" PRId64 " %" PRId64 "\n",
            (uintmax_t)client->inode,
            client->ticket,
            client->mode ? client->mode : '-',
            client_state_names[client->state],
            (int)client->pid,
            client->queued_at,
            client->granted_at
        );
    }

    const bool write_failed = ferror(file);
    if (fclose(file) != 0)
        return false;
    if (write_failed) {
        errno = EIO;
        return false;
    }
    return true;
}

bool journal_find (FILE *file, ino_t inode, struct Client *client) {
    rewind(file);

    char line[JOURNAL_LINE_SIZE];
    while (fgets(line, sizeof line, file)) {
        uintmax_t entry_inode;
        uint64_t ticket;
        char mode;
        char state_name[16];
        int64_t queued_at, granted_at;
        // PID is read from the socket.
        const int count = sscanf(
            line, "%ju %" SCNu64 " %c %15s %*d %" SCNd64 " %" SCNd64,
            &entry_inode, &ticket, &mode, state_name, &queued_at, &granted_at
        );
        if (count != 6 || (ino_t)entry_inode != inode)
            continue;

        for (size_t i = 0; i < sizeof client_state_names / sizeof *client_state_names; ++i) {
            if (strcmp(state_name, client_state_names[i]) != 0)
                continue;

            client->state = (enum ClientState)i;
            client->mode = mode == 'R' || mode == 'W' ? mode : 0;
            client->ticket = ticket;
            client->queued_at = queued_at;
            client->granted_at = granted_at;
            // Client can't be in "asked" state and have a mode
            // it can't be in any other state and have no mode either.
            return (client->mode != 0) == (client->state != CLIENT_ASKED);
        }
        return false;
    }
    return false;
}
