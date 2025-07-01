#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>

#define QCOW2_HEADER_SIZE 104
#define QCOW2_MAGIC 0x514649FB

#define L2_OFFSET_MASK 0x00FFFFFFFFFFFF00
#define STANDARD_CLUSTER_OFFSET_MASK 0x00FFFFFFFFFFFF00 /* Bits 9-55 are offset of standard cluster */
#define CLUSTER_TYPE_BIT (1UL << 62) /* 0 for standard, 1 for compressed cluster */
#define ALLOCATED_ENTRY_BIT (1UL << 63) /* Bit 63 is the allocated bit for standard cluster */


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

    /* Additional fields */
    uint8_t compression_type;

    /* header must be a multiple of 8 */
    uint8_t padding[7];
} __attribute__((packed));

#define SWAP_BE_TO_LE(size, x) \
    header->x = __builtin_bswap ##size(header->x)
