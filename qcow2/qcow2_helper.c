#include "qcow_helper.h"

static void transform_header_be_to_le(struct qcow2_header* header){
    SWAP_BE_TO_LE(32, magic);
    SWAP_BE_TO_LE(32, version);
    SWAP_BE_TO_LE(64, backing_file_offset);
    SWAP_BE_TO_LE(32, backing_file_size);
    SWAP_BE_TO_LE(32, cluster_bits);
    SWAP_BE_TO_LE(64, size);
    SWAP_BE_TO_LE(32, crypt_method);
    SWAP_BE_TO_LE(32, l1_size);
    SWAP_BE_TO_LE(64, l1_table_offset);
    SWAP_BE_TO_LE(64, refcount_table_offset);
    SWAP_BE_TO_LE(32, refcount_table_clusters);
    SWAP_BE_TO_LE(32, nb_snapshots);
    SWAP_BE_TO_LE(64, snapshots_offset);
    SWAP_BE_TO_LE(64, incompatible_features);
    SWAP_BE_TO_LE(64, compatible_features);
    SWAP_BE_TO_LE(64, autoclear_features);
    SWAP_BE_TO_LE(32, refcount_order);
    SWAP_BE_TO_LE(32, header_length);
}

char* qcow2_get_backing_file(struct qcow2_header* header, int fd){
    int err, backing_file_name_size;
    char* backing_file_name;

    if(header->backing_file_offset != 0){
        backing_file_name_size = header->backing_file_size+1;
        backing_file_name = malloc(backing_file_name_size);
        if(backing_file_name == NULL){
            fprintf(stderr, "Failed to allocate for backing file name");
            exit(EXIT_FAILURE);
        }
        lseek(fd, header->backing_file_offset, SEEK_SET);
        err = read(fd, backing_file_name, header->backing_file_size);
        if(err < 0){
            fprintf(stderr, "Couldn't read backing file: %s (%d)\n", strerror(errno), errno);
            exit(EXIT_FAILURE);
        }
        backing_file_name[backing_file_name_size-1] = '\0';
        return backing_file_name;
    }
    return NULL;
}

uint64_t* get_l1_offset(struct qcow2_header* header, int fd){
    int i, err = 0;
    uint64_t* raw_l1 = NULL;
    uint64_t l1_offset = header->l1_table_offset;
    uint32_t l1_table_size = sizeof(uint64_t) * header->l1_size;

    raw_l1 = malloc(l1_table_size);
    if(raw_l1 == NULL){
        fprintf(stderr, "Couldn't allocate %d byte for L1 table\n", l1_table_size);
        return NULL;
    }

    err = pread(fd, raw_l1, l1_table_size, l1_offset);
    if(err < 0){
        fprintf(stderr, "Couldn't read L1 table\n");
        free(raw_l1);
        return NULL;
    }

    for(i = 0; i < header->l1_size; i++){
        raw_l1[i] = (__builtin_bswap64(raw_l1[i]) & L2_OFFSET_MASK);
    }

    return raw_l1;
}

uint64_t* get_l2_table(struct qcow2_header* header, int fd, uint64_t offset){
    int i;
    uint64_t* raw_l2 = NULL;
    uint64_t cluster_size = (1 << header->cluster_bits);
    uint64_t nb_l2_entries = (cluster_size / sizeof(uint64_t));

    raw_l2 = malloc(cluster_size);
    if(raw_l2 == NULL){
        fprintf(stderr, "Couldn't allocate %lu byte for L1 table\n", cluster_size);
        return NULL;
    }

    pread(fd, raw_l2, cluster_size, offset);

    for(i = 0; i < nb_l2_entries; i++){
        raw_l2[i] = __builtin_bswap64(raw_l2[i]);
    }

    return raw_l2;
}

int is_l2_allocated(uint64_t l2_entry){
    if((l2_entry & CLUSTER_TYPE_BIT) != 0){
        fprintf(stderr, "Cluster is compressed\n");
        exit(EXIT_FAILURE); //TODO: Read compressed clusters
    }
    return ((l2_entry & ALLOCATED_ENTRY_BIT) != 0) || ((l2_entry & STANDARD_CLUSTER_OFFSET_MASK) != 0);
}

uint64_t get_cluster_to_byte(uint64_t allocated_clusters, uint64_t cluster_size){
    return allocated_clusters * cluster_size;
}

void mark_l1_unallocated(char* bitmap, int i){}

void mark_l2_unallocated(char* bitmap, int i, int j){}

void set_bit(char* m, int bit, int val){
    *m |= (val << bit);
}

void dump_bitmap(struct qcow2_header* header, int fd, uint64_t *l1_table){
    int i, n;
    char* bitmap = NULL;
    uint64_t cluster_size = (1 << header->cluster_bits); //cluster size in bytes
    uint64_t total_blocks, bitmap_size;
    uint64_t nb_l2_entries = (cluster_size / sizeof(uint64_t)); //Number of L2 in a L1 entry

	total_blocks = header->size / cluster_size;
    bitmap_size = total_blocks >> 3; // This transform our number of bits in a number of bytes for allocation
    //Does VHD use sectors of 512 for the bitmap it dumps? Nope, it uses 2MiB. Do we want to use 2MiB to reduce QCOW2 size allocation? We would need a way to transform x 64KiB blocks in a 2MiB block.
    bitmap = malloc(bitmap_size);
    memset(bitmap, 0, bitmap_size);
    uint64_t nb_byte_for_l1 = nb_l2_entries / 8; //Number of byte in the bitmap for a full L1

    #pragma omp parallel for num_threads(4)
    for(i = 0; i < header->l1_size; i++){
        int j;
        uint64_t *l2_table = NULL;
        uint64_t l1_entry = l1_table[i];
        if(l1_entry != 0){
            l2_table = get_l2_table(header, fd, l1_entry); if(l2_table == NULL) { fprintf(stderr, "Couldn't get L2 entry\n"); exit(EXIT_FAILURE); }
            char* base_l1_bitmap = bitmap + (i * nb_byte_for_l1);
            for(j = 0; j < nb_l2_entries; j++){
                if(is_l2_allocated(l2_table[j])){
                    //Mark L2 entry allocated

                    int mementry = j/8;
                    int bit = j%8;
                    set_bit(&(base_l1_bitmap[mementry]), bit, 1);
                }
                else {
                    // Mark L2 entry as not allocated
                    mark_l2_unallocated(bitmap, i, j); // The bytes are already zeroed, we don't need to do anything
                }
            }
            free(l2_table);
        }
        else{
            //Mark L1 (and subsequent L2) non allocated
            mark_l1_unallocated(bitmap, i); // The bytes are already zeroed, we don't need to do anything
            // memset(base_l1_bitmap, 0, nb_byte_for_l1); //Mark the whole L1 as being unused
        }
    }

    n = write(STDOUT_FILENO, bitmap, bitmap_size);
    if (n < 0){
        fprintf(stderr, "Error writing bitmap to stdout");
    }
    free(bitmap);
}

int get_allocated_blocks(struct qcow2_header* header, int fd, uint64_t *l1_table){
    uint64_t allocated_clusters = 0;
    int i, cluster_size = (1 << header->cluster_bits), nb_l2_entries = cluster_size / (sizeof(uint64_t));


    #pragma omp parallel for num_threads(4) reduction (+:allocated_clusters)
    for(i = 0; i < header->l1_size; i++){
        int j;
        uint64_t *l2_table = NULL;
        uint64_t l1_entry = l1_table[i];
        if(l1_entry != 0){
            l2_table = get_l2_table(header, fd, l1_entry);
            if(l2_table == NULL){
                fprintf(stderr, "Couldn't get L2 Table");
            }
            for(j = 0; j < nb_l2_entries; j++){
                if(is_l2_allocated(l2_table[j])){
                    allocated_clusters += 1;
                }
            }
            free(l2_table);
        }
    }
    return allocated_clusters;
}

int main(int argc, char* argv[]){
    struct qcow2_header* header = NULL;
    char * command, * filename = NULL, * backing_file_name = NULL;
    int fd, err = 0, ret = EXIT_SUCCESS;
    uint64_t *l1_table = NULL, cluster_size = 0, allocated_clusters = 0, allocated_byte = 0;

    if(argc != 3){
        fprintf(stderr, "Need an argument\n");
        exit(EXIT_FAILURE);
    }
    command = argv[1];
    filename = argv[2];
    fd = open(filename, O_RDONLY);
    if(fd < 0){
        fprintf(stderr, "Opening file %s failed with error %s (%d)\n", filename, strerror(errno), errno);
        ret = EXIT_FAILURE;
        goto exit_filename;
    }

    // printf("Reading header from %s\n", filename);

    header = malloc(QCOW2_HEADER_SIZE);
    if(header == NULL){
        fprintf(stderr, "Couldn't allocate header\n");
        ret = EXIT_FAILURE;
        goto close_and_exit;
    }

    err = pread(fd, header, QCOW2_HEADER_SIZE, 0);
    if(err < 0){
        fprintf(stderr, "Failed reading file\n");
        ret = EXIT_FAILURE;
        goto close;
    }

    transform_header_be_to_le(header);

    if(header->magic != QCOW2_MAGIC){
        fprintf(stderr, "MAGIC is wrong\n");
        goto close;
    }

    cluster_size = (1 << header->cluster_bits);

    // printf("Version: %d\n", header->version);
    // backing_file_name = qcow2_get_backing_file(header, fd);
    // printf("Backing file: %s\n", backing_file_name);

    l1_table = get_l1_offset(header, fd);
    if(l1_table == NULL){
        fprintf(stderr, "Couldn't read L1 Table\n");
        ret = EXIT_FAILURE;
        goto free_backing;
    }

    if(!strcmp("bitmap", command)){
        dump_bitmap(header, fd, l1_table);
    }
    else if(!strcmp("allocated", command)){
        allocated_clusters = get_allocated_blocks(header, fd, l1_table);
        allocated_byte = get_cluster_to_byte(allocated_clusters, cluster_size);
        printf("%lu\n", allocated_byte);
    }
    else{
        fprintf(stderr, "Command %s is unknown.\n", command);
        ret = EXIT_FAILURE;
    }

    if(l1_table != NULL){
        free(l1_table);
    }

free_backing:
    if(backing_file_name != NULL)
        free(backing_file_name);
close:
    free(header);
close_and_exit:
    close(fd);
exit_filename:
    exit(ret);
}
