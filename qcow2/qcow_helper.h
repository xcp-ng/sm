#include <errno.h>
#include <fcntl.h>
#include <fnmatch.h>
#include <getopt.h>
#include <libgen.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define QCOW2_HEADER_SIZE             104
#define QCOW2_MAGIC                   0x514649FB

#define L2_OFFSET_MASK                0x00FFFFFFFFFFFF00
#define STANDARD_CLUSTER_OFFSET_MASK  0x00FFFFFFFFFFFF00 /* Bits 9-55 are offset of standard cluster */

#define COMPRESSED_SECTOR_SIZE     512
#define COMPRESSED_SECTOR_MASK     (COMPRESSED_SECTOR_SIZE - 1)

#define CLUSTER_TYPE_BIT           62
#define CLUSTER_TYPE_MASK          (1UL << CLUSTER_TYPE_BIT) /* 0 for standard, 1 for compressed cluster */
#define ALLOCATED_ENTRY_MASK       (1UL << 63)               /* Bit 63 is the allocated bit for standard cluster */

/* Incompatible features */
#define INCOMPATIBLE_FEATURE_EXTENDED_L2 0x0010

#define NAME_MAX_SIZE 512

/* Custom header */
#define CUSTOM_HEADER_TYPE 0x76617465  //vate: it is easy to recognize with hexdump -C

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

typedef struct {
    const char *name;
    void (*fn)(int argc, char **argv);
    void (*usage)(void);
} command_t;

struct custom_header{
    uint32_t type;
    uint32_t length;
    uint64_t data;
};

struct qcow2_header {
    uint32_t magic;
    uint32_t version;
    uint64_t backing_file_offset;
    uint32_t backing_file_size;
    uint32_t cluster_bits;
    uint64_t size; /* in bytes */
    uint32_t crypt_method;
    uint32_t l1_size; /* XXX: save number of clusters instead ? */
    uint64_t l1_table_offset;
    uint64_t refcount_table_offset;
    uint32_t refcount_table_clusters;
    uint32_t nb_snapshots;
    uint64_t snapshots_offset;

    /* The following fields are only valid for version >= 3 */
    uint64_t incompatible_features;
    uint64_t compatible_features;
    uint64_t autoclear_features;

    uint32_t refcount_order;
    uint32_t header_length;
} __attribute__((packed));

#define BE_TO_HOST(size, x) \
    header->x = be ##size## toh(header->x)

static inline uint64_t qcow2_cluster_size(const struct qcow2_header *header) {
    return (uint64_t)1 << header->cluster_bits;
}

static inline int qcow2_extended_l2(const struct qcow2_header *header) {
    return (header->version == 3) && (header->incompatible_features & INCOMPATIBLE_FEATURE_EXTENDED_L2);
}

static inline uint64_t qcow2_nb_l2_entries(uint64_t cluster_size, int extended_l2) {
    return extended_l2 ? cluster_size / (sizeof(uint64_t) * 2) : cluster_size / sizeof(uint64_t);
}
