#define _GNU_SOURCE // For `struct ucred`.

#include "fairlock.h"

int client_compare_tickets (const void *a, const void *b) {
	const uint64_t ticket_a = ((const struct Client *)a)->ticket;
	const uint64_t ticket_b = ((const struct Client *)b)->ticket;
	return (ticket_a > ticket_b) - (ticket_a < ticket_b);
}

bool client_has_lock (const struct Client *client) {
	return client->state == CLIENT_GRANTED || client->state == CLIENT_OWNED;
}

pid_t client_get_pid (int sock) {
	struct ucred credentials;
	socklen_t length = sizeof credentials;
	return getsockopt(sock, SOL_SOCKET, SO_PEERCRED, &credentials, &length) == 0 ? credentials.pid : 0;
}

// -----------------------------------------------------------------------------

void client_close (int sock) {
	// Shutdown to make systemd drop its copy.
	shutdown(sock, SHUT_RDWR);
	close(sock);
}

bool client_read_mode (struct Client *client) {
	char mode;

	if (read(client->sock, &mode, 1) != 1 || (mode != 'R' && mode != 'W'))
		return false;

	client->mode = mode;
	client->state = CLIENT_QUEUED;
	client->queued_at = get_current_time();
	return true;
}

bool client_read_data (const struct ServerState *state, struct Client *client) {
	char buffer[128];
	const ssize_t n = read(client->sock, buffer, sizeof(buffer) - 1);
	if (n <= 0)
		return false;
	buffer[n] = '\0';

	// Any data sent by a granted client is an acknowledgement of the lock.
	if (client->state == CLIENT_GRANTED)
		client->state = CLIENT_OWNED;

	syslog(LOG_INFO, "%s sent '%s'\n", state->lock_path, buffer);
	return true;
}

int client_new(struct Client *client, const int sock, const uint64_t ticket) {
	struct stat st;
	if (fstat(sock, &st) < 0) {
		close(sock);
		return 1;
	}

	client->mode = 0;
	client->state = CLIENT_ASKED;
	client->lock_sent = false;
	client->accepted_at = get_current_time();
	client->queued_at = 0;
	client->granted_at = 0;
	client->sock = sock;
	client->ticket = ticket;
	client->inode = st.st_ino;
	client->pid = client_get_pid(sock);

	return 0;
}
