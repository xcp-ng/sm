#ifndef FAIRLOCK_H
#define FAIRLOCK_H

#include <assert.h>

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include <systemd/sd-daemon.h>

#define MAX_CLIENTS 128 // Keep in sync with `FileDescriptorStoreMax=` in fairlock@.service.
#define MODE_TIMEOUT 5000 // In milliseconds.
#define JOURNAL_RETRY_DELAY 100 // In milliseconds.

enum ClientState {
    CLIENT_ASKED, // Connected, mode not received yet.
    CLIENT_QUEUED, // Mode received, waiting for the lock.
    CLIENT_GRANTED, // Lock given, "LOCK" sent (or to send again after a restart).
    CLIENT_OWNED // Client acknowledged the lock by sending data back.
    // Released clients are simply removed.
};

struct Client {
    int sock;
    char mode; // 0, 'R' or 'W'.
    enum ClientState state;
    bool lock_sent; // Not journaled: restored granted clients get "LOCK" again.
    uint64_t ticket; // Position in the FIFO, preserved across restarts.
    ino_t inode; // The same in systemd's fd store and after a restart.
    pid_t pid;
    int64_t accepted_at; // Used to expire clients that never send their mode. In milliseconds.
    int64_t queued_at; // When the mode was received, 0 if unknown. In milliseconds.
    int64_t granted_at; // When the lock was given, 0 if unknown. In milliseconds.
};

struct ServerState {
    const char *lock_path;
    const char *journal_path; // Optional: journaling is disabled without it.

    int server_sock;
    struct Client clients[MAX_CLIENTS];
    int client_count;
    uint64_t next_ticket;
    bool dirty; // Journal and status must be updated.
    bool journal_failed;

    int reader_count;
    bool has_writer;

    int64_t watchdog_interval; // In milliseconds, 0 if disabled.
    int64_t watchdog_next_ping;
};

// journal
bool journal_write (const struct ServerState *state, const char *path);
bool journal_find (FILE *file, ino_t inode, struct Client *client);

// client
bool client_has_lock (const struct Client *client);
bool client_read_mode (struct Client *client);
bool client_read_data (const struct ServerState *state, struct Client *client);
int client_new (struct Client *client, int sock, uint64_t ticket);
int client_compare_tickets (const void *a, const void *b);
pid_t client_get_pid (int sock);
void client_close (int sock);

// utils
int64_t get_current_time (void);

#endif //FAIRLOCK_H
