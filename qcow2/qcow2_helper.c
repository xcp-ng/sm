#include "qcow_helper.h"
#include "lvm-util.h"

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

char* qcow2_get_backing_file(struct qcow2_header* header, int fd, uint64_t device_offset){
    int err, backing_file_name_size;
    char* backing_file_name;

    if(header->backing_file_offset != 0){
        backing_file_name_size = header->backing_file_size+1;
        backing_file_name = malloc(backing_file_name_size);
        if(backing_file_name == NULL){
            fprintf(stderr, "Failed to allocate for backing file name");
            exit(EXIT_FAILURE);
        }
        err = pread(fd, backing_file_name, header->backing_file_size, header->backing_file_offset+device_offset);
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
        fprintf(stderr, "Couldn't read L1 table: %s (%d)\n",
                strerror(errno), errno);
        free(raw_l1);
        return NULL;
    }

    for(i = 0; i < header->l1_size; i++){
        raw_l1[i] = (__builtin_bswap64(raw_l1[i]) & L2_OFFSET_MASK);
    }

    return raw_l1;
}

uint64_t* get_l2_table(struct qcow2_header* header, int fd, uint64_t offset, uint64_t nb_l2_entries, int extended_l2){
    int i;
    ssize_t bytes_read;
    uint64_t* raw_l2 = NULL;
    uint64_t cluster_size = (1 << header->cluster_bits);

    raw_l2 = malloc(cluster_size);
    if(raw_l2 == NULL){
        fprintf(stderr, "Couldn't allocate %lu byte for L1 table\n", cluster_size);
        return NULL;
    }

    bytes_read = pread(fd, raw_l2, cluster_size, offset);
    if (bytes_read == -1) {
        fprintf(stderr, "Couldn't read L2 table: %s (%d)\n",
                strerror(errno), errno);
        free(raw_l2);
        return NULL;
    }

    for(i = 0; i < nb_l2_entries * (extended_l2 ? 2 : 1); i++){
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

int is_extended_l2_allocated(uint64_t l2_entry_lo, uint64_t l2_entry_hi){
    if((l2_entry_lo & CLUSTER_TYPE_BIT) != 0){
        fprintf(stderr, "Cluster is compressed\n");
        exit(EXIT_FAILURE); //TODO: Read compressed clusters
    }
    return l2_entry_hi & 0xffffffff;
}

uint32_t count_set_bits(uint32_t alloc_status_bitmap)
{
    uint32_t count = 0;

    if (alloc_status_bitmap == 0)
        return 0;

    while (alloc_status_bitmap) {
        alloc_status_bitmap &= alloc_status_bitmap - 1;
        count++;
    }

    return count;
}

uint32_t get_extended_l2_allocated(uint64_t l2_entry_lo, uint64_t l2_entry_hi){
    if((l2_entry_lo & CLUSTER_TYPE_BIT) != 0){
        fprintf(stderr, "Cluster is compressed\n");
        exit(EXIT_FAILURE); //TODO: Read compressed clusters
    }
    return count_set_bits(l2_entry_hi & 0xffffffff);
}

uint64_t get_allocated_clusters(uint64_t nb_l2_entries, uint64_t *l2_table, int extended_l2)
{
    uint64_t allocated_clusters = 0;
    int j;
    for(j = 0; j < nb_l2_entries; j++){
        if (extended_l2) {
            allocated_clusters += get_extended_l2_allocated(l2_table[j*2], l2_table[j*2+1]);
        } else {
            if(is_l2_allocated(l2_table[j])){
                allocated_clusters += 1;
            }
        }
    }
    return allocated_clusters;
}

uint64_t get_cluster_to_byte(uint64_t allocated_clusters, uint64_t cluster_size, int extended_l2){
    if (extended_l2) {
        return allocated_clusters * (cluster_size / 32);
    }
    return allocated_clusters * cluster_size;
}

void mark_l1_unallocated(char* bitmap, int i){}

void mark_l2_unallocated(char* bitmap, int i, int j){}

void set_bit(char* m, int bit, int val){
    *m |= (val << bit);
}

void set_l1_bitmap(char *base_l1_bitmap, uint64_t *l2_table, uint64_t nb_l2_entries, int extended_l2) {
    int j;
    int mementry;
    int bit;

    for (j = 0; j < nb_l2_entries; j++) {
        if (extended_l2) {
            if(!is_extended_l2_allocated(l2_table[j*2], l2_table[j*2+1])) {
                continue;
            }
        } else {
            if(!is_l2_allocated(l2_table[j])){
                continue;
            }
        }
        mementry = j/8;
        bit = j%8;
        //Mark L2 entry allocated
        set_bit(&(base_l1_bitmap[mementry]), bit, 1);
    }
}

void dump_bitmap(struct qcow2_header* header, int fd, uint64_t *l1_table, uint64_t nb_l2_entries, int extended_l2){
    int i, n;
    char* bitmap = NULL;
    uint64_t cluster_size = (1 << header->cluster_bits); //cluster size in bytes
    uint64_t total_blocks, bitmap_size;

    total_blocks = header->size / cluster_size;
    bitmap_size = total_blocks >> 3; // This transform our number of bits in a number of bytes for allocation
    //Does VHD use sectors of 512 for the bitmap it dumps? Nope, it uses 2MiB. Do we want to use 2MiB to reduce QCOW2 size allocation? We would need a way to transform x 64KiB blocks in a 2MiB block.
    bitmap = malloc(bitmap_size);
    memset(bitmap, 0, bitmap_size);
    uint64_t nb_byte_for_l1 = nb_l2_entries / 8; //Number of byte in the bitmap for a full L1

    #pragma omp parallel for num_threads(4)
    for(i = 0; i < header->l1_size; i++){
        uint64_t *l2_table = NULL;
        uint64_t l1_entry = l1_table[i];
        if(l1_entry != 0){
            l2_table = get_l2_table(header, fd, l1_entry, nb_l2_entries, extended_l2);
            if(l2_table == NULL) {
                fprintf(stderr, "Couldn't get L2 table\n");
                exit(EXIT_FAILURE);
            }
            char* base_l1_bitmap = bitmap + (i * nb_byte_for_l1);
            set_l1_bitmap(base_l1_bitmap, l2_table, nb_l2_entries, extended_l2);
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

int get_allocated_blocks(struct qcow2_header* header, int fd, uint64_t *l1_table, uint64_t nb_l2_entries, int extended_l2){
    uint64_t allocated_clusters = 0;
    int i;

    #pragma omp parallel for num_threads(4) reduction (+:allocated_clusters)
    for(i = 0; i < header->l1_size; i++){
        uint64_t *l2_table = NULL;
        uint64_t l1_entry = l1_table[i];
        if(l1_entry != 0){
            l2_table = get_l2_table(header, fd, l1_entry, nb_l2_entries, extended_l2);
            if(l2_table == NULL){
                fprintf(stderr, "Couldn't get L2 Table");
                exit(EXIT_FAILURE);
            }
            allocated_clusters += get_allocated_clusters(nb_l2_entries, l2_table, extended_l2);
            free(l2_table);
        }
    }
    return allocated_clusters;
}

static int qcow2_open(const char *filename, struct qcow2_header *header, int *fd_out) {
    int err;
    int fd;

    fd = open(filename, O_RDONLY | O_DIRECT);
    if (fd < 0) {
        fprintf(stderr, "Opening file %s failed: %s (%d)\n", filename, strerror(errno), errno);
        return -1;
    }
    err = pread(fd, header, QCOW2_HEADER_SIZE, 0);
    if (err < 0) {
        fprintf(stderr, "Failed reading file\n");
        close(fd);
        return -1;
    }
    transform_header_be_to_le(header);
    if (header->magic != QCOW2_MAGIC) {
        fprintf(stderr, "MAGIC is wrong\n");
        close(fd);
        return -1;
    }

    *fd_out = fd;
    return 0;
}

static void usage_bitmap(void) { fprintf(stderr, "Usage: bitmap -f <file>\n"); }

static void cmd_bitmap(int argc, char **argv) {
    char *filename = NULL;
    int opt, fd;
    struct qcow2_header header;
    uint64_t *l1_table;

    while ((opt = getopt(argc, argv, "f:")) != -1) {
        switch (opt) {
        case 'f': filename = optarg; break;
        default:
            usage_bitmap();
            exit(EXIT_FAILURE);
        }
    }

    if (filename == NULL) {
        usage_bitmap();
        exit(EXIT_FAILURE);
    }

    if (qcow2_open(filename, &header, &fd) < 0)
        exit(EXIT_FAILURE);

    l1_table = get_l1_offset(&header, fd);
    if (l1_table == NULL) {
        fprintf(stderr, "Couldn't read L1 Table\n");
        close(fd);
        exit(EXIT_FAILURE);
    }

    uint64_t cluster_size = qcow2_cluster_size(&header);
    int extended_l2 = qcow2_extended_l2(&header);
    dump_bitmap(&header, fd, l1_table, qcow2_nb_l2_entries(cluster_size, extended_l2), extended_l2);

    free(l1_table);
    close(fd);
}

static void usage_allocated(void) { fprintf(stderr, "Usage: allocated -f <file>\n"); }

static void cmd_allocated(int argc, char **argv) {
    char *filename = NULL;
    int opt, fd;
    struct qcow2_header header;
    uint64_t *l1_table;

    while ((opt = getopt(argc, argv, "f:")) != -1) {
        switch (opt) {
        case 'f': filename = optarg; break;
        default:
            usage_allocated();
            exit(EXIT_FAILURE);
        }
    }

    if (filename == NULL) {
        usage_allocated();
        exit(EXIT_FAILURE);
    }

    if (qcow2_open(filename, &header, &fd) < 0)
        exit(EXIT_FAILURE);

    l1_table = get_l1_offset(&header, fd);
    if (l1_table == NULL) {
        fprintf(stderr, "Couldn't read L1 Table\n");
        close(fd);
        exit(EXIT_FAILURE);
    }
    uint64_t cluster_size = qcow2_cluster_size(&header);
    int extended_l2 = qcow2_extended_l2(&header);
    uint64_t clusters = get_allocated_blocks(&header, fd, l1_table, qcow2_nb_l2_entries(cluster_size, extended_l2), extended_l2);
    uint64_t bytes = get_cluster_to_byte(clusters, cluster_size, extended_l2);
    printf("%lu\n", bytes);
    free(l1_table);
    close(fd);
}

struct scan_info {
    char name[NAME_MAX_SIZE]; //SIZE decided democratically
    uint64_t capacity;
    uint64_t size;
    bool hidden;
    char parent[NAME_MAX_SIZE];
};

static struct lv* lv_find_by_name(const struct lv *lvs, int lv_count, const char *name) {
    int i;
    for (i = 0; i < lv_count; i++)
        if (strcmp(lvs[i].name, name) == 0)
            return (struct lv *)&lvs[i];
    return NULL;
}

struct lv* lv_filter_by_pattern(const struct vg *vg, const char *pattern, int *lv_count) {
    int i, j = 0;
    struct lv *result;

    result = malloc(sizeof(struct lv) * vg->lv_cnt);
    if (result == NULL) {
        *lv_count = 0;
        return NULL;
    }

    for (i = 0; i < vg->lv_cnt; i++) {
        if (fnmatch(pattern, vg->lvs[i].name, FNM_PATHNAME | FNM_EXTMATCH) == 0)
            result[j++] = vg->lvs[i];
    }

    *lv_count = j;
    return result;
}

struct qcow2_header* get_header_from_device(struct lv* lv, int fd){
    struct qcow2_header* header = NULL;
    int err;

    header = malloc(QCOW2_HEADER_SIZE);
    if (header == NULL) {
        fprintf(stderr, "Couldn't allocate header\n");
        return NULL;
    }
    err = pread(fd, header, QCOW2_HEADER_SIZE, lv->first_segment.pe_start); //OFFSET need to be offset of LV in device
    if (err < 0) {
        fprintf(stderr, "Failed reading file %s\n", lv->name);
        goto err_free_header;
    }
    transform_header_be_to_le(header);
    if (header->magic != QCOW2_MAGIC) {
        fprintf(stderr, "MAGIC is wrong for %s\n", lv->name);
        goto err_free_header;
    }

    return header;

err_free_header:
    free(header);
    return NULL;
}

char* get_backing_file_from_device(struct qcow2_header* header, struct lv* lv, int fd){
        if(header->backing_file_offset >= lv->first_segment.pe_size){
            fprintf(stderr, "Backing file is not in first segment for LV %s\n", lv->name);
            exit(EXIT_FAILURE);
            // return NULL; //TODO: We need to diff not having a backing file and it erroring here.
        }
        return qcow2_get_backing_file(header, fd, lv->first_segment.pe_start);
}

static uint32_t read_data_from_qcow2_header(int fd, size_t offset){
    uint32_t data;
    if(pread(fd, &data, 4, offset) < 1){
        exit(EXIT_FAILURE); //TODO: Handle error correctly
    }
    data = __builtin_bswap32(data);
    return data;
}

void transform_custom_header_bswap(struct custom_header* custom_header){
    custom_header->type = __builtin_bswap32(custom_header->type);
    custom_header->length = __builtin_bswap32(custom_header->length);
    // custom_header->custom_header_data = __builtin_bswap64(custom_header->custom_header_data);
    /**
     The data in the custom header is little endian when it should be big endian in qcow2
     It's because the python code writing the hidden status wrote directly at the offset of the data
     like if it was 1 octet.
    */
}

size_t find_custom_header(struct qcow2_header* header, int fd, uint64_t device_offset){
    size_t current_offset;
    uint32_t header_length = 72, ext_type, ext_len;

    if(header->version == 3){
        header_length = header->header_length;
    }

    current_offset = header_length;
    current_offset += device_offset;
    
    do{
        ext_type = read_data_from_qcow2_header(fd, current_offset);
        ext_len = read_data_from_qcow2_header(fd, current_offset+4);
        if(ext_type == CUSTOM_HEADER_TYPE){
            // A custom header is already there
            return current_offset;
        }
        current_offset += 8 + ((ext_len + 7) & ~(uint32_t)7);
    } while(ext_type != 0);

    return 0;
}

static int fill_scan_info_from_lv(struct lv *lv, struct scan_info *info) {
    int fd;

    strncpy(info->name, lv->name, NAME_MAX_SIZE);
    info->size = lv->size;

    /* Getting header from the underlying device*/
    fd = open(lv->first_segment.device, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "Opening device %s failed: %s (%d)\n", lv->first_segment.device, strerror(errno), errno);
        return -1;
    }
    struct qcow2_header* header = get_header_from_device(lv, fd);

    info->capacity = header->size;

    /* Getting parent if it exist */
    char* backing_file_name = get_backing_file_from_device(header, lv, fd);
    if(backing_file_name){
        char* parent_lv_name = basename(backing_file_name); //Transform the backing name from full path of the LV to just the LV name
        strncpy(info->parent, parent_lv_name, NAME_MAX_SIZE);
        // strncpy(info->parent, backing_file_name, strlen(backing_file_name));
        //The existing code in qcow2util.py might need the full path though
        free(backing_file_name);
    }
    else{
        strncpy(info->parent, "none", 5);
    }

    /* Getting hidden from custom header */
    size_t custom_header_offset = find_custom_header(header, fd, lv->first_segment.pe_start);
    if(custom_header_offset){
        struct custom_header custom_header;
        pread(fd, &custom_header, sizeof(struct custom_header), custom_header_offset);
        transform_custom_header_bswap(&custom_header);
        info->hidden = custom_header.data;
    }
    else{
        info->hidden = 0;
    }

    free(header);
    close(fd);
    return 0;
}

struct scan_info* get_infos(char* vg_name, int* lv_count, const char* pattern, int include_parents) {
    int i, matched_count, err;
    struct vg vg;
    struct lv *matched_lvs;
    struct scan_info *infos, *info;

    err = lvm_scan_vg(vg_name, &vg);
    if(err < 0){
        fprintf(stderr, "lvm_scan_vg failed %d\n", err);
        return NULL;
    }
    matched_lvs = lv_filter_by_pattern(&vg, pattern, &matched_count);

    infos = calloc(vg.lv_cnt, sizeof(struct scan_info));
    if(infos == NULL){
        fprintf(stderr, "Failed to allocate scan_info array\n");
        goto alloc_info_err;
    }

    for(i = 0; i < matched_count; i++){
        if(fill_scan_info_from_lv(&matched_lvs[i], &infos[i]) < 0){
            goto scan_info_err;
        }
    }

    if(include_parents){
        for (i = 0; i < matched_count; i++){
            struct lv* parent_lv;
            info = &infos[i];

            if(strcmp(info->parent, "none") == 0)
                continue;

            if(lv_find_by_name(matched_lvs, matched_count, info->parent) != NULL)
                continue;

            parent_lv = lv_find_by_name(vg.lvs, vg.lv_cnt, info->parent);
            if(parent_lv != NULL){
                matched_lvs[matched_count] = *parent_lv;
                if(fill_scan_info_from_lv(&matched_lvs[matched_count], &infos[matched_count]) < 0){
                    goto scan_info_err;
                }
                matched_count++;
            }
            else{
                fprintf(stderr, "scan-error: %s not found\n", info->parent);
                goto scan_info_err;
            }
        }
    }

    free(matched_lvs);
    lvm_free_vg(&vg);

    *lv_count = matched_count;
    return infos;

scan_info_err:
    free(infos);
alloc_info_err:
    free(matched_lvs);
    lvm_free_vg(&vg);
    return NULL;
}

static void usage_scan(void) { fprintf(stderr, "Usage: scan -l <vg> -m <match filter> [-a scan parents]\n"); }

static void cmd_scan(int argc, char **argv) {
    char *vg_name = NULL, *pattern = NULL;
    int i, opt, lv_count, include_parents = 0;

    while ((opt = getopt(argc, argv, "l:m:a")) != -1) {
        switch (opt) {
        case 'l': vg_name = optarg; break;
        case 'm': pattern = optarg; break;
        case 'a': include_parents = 1; break;
        default:
            usage_scan();
            exit(EXIT_FAILURE);
        }
    }
    if(vg_name == NULL || pattern == NULL){
        usage_scan();
        exit(EXIT_FAILURE);
    }

    struct scan_info *infos = get_infos(vg_name, &lv_count, pattern, include_parents);
    if(infos == NULL){
        exit(EXIT_FAILURE);
    }

    for(i = 0; i < lv_count; i++){
        struct scan_info info = infos[i];
        printf("qcow2=%s capacity=%lu size=%lu hidden=%d parent=%s\n",
               info.name, info.capacity, info.size, info.hidden, info.parent);
    }
    free(infos);
}

/* Defined here because they are co-dependent on commands */
static void usage_help(void);
static void cmd_help(int argc, char **argv);

static const command_t commands[] = {
    {"bitmap",    cmd_bitmap,    usage_bitmap},
    {"allocated", cmd_allocated, usage_allocated},
    {"scan",      cmd_scan,      usage_scan},
    {"help",      cmd_help,      usage_help},
};

static void usage_help(void) { fprintf(stderr, "Usage: help\n"); }

static void cmd_help(int argc, char **argv) {
    int i;
    fprintf(stderr, "Usage: qcow2_helper <command> [options]\n\nCommands:\n");
    for (i = 0; i < ARRAY_SIZE(commands); i++)
        commands[i].usage();
}

int main(int argc, char *argv[]) {
    int i;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command> [options]\nRun '%s help' for a list of commands.\n", argv[0], argv[0]);
        exit(EXIT_FAILURE);
    }

    for (i = 0; i < ARRAY_SIZE(commands); i++) {
        if (!strcmp(commands[i].name, argv[1])) {
            commands[i].fn(argc - 1, argv + 1);
            return EXIT_SUCCESS;
        }
    }

    fprintf(stderr, "Command %s is unknown.\nRun '%s help' for a list of commands.\n", argv[1], argv[0]);
    return EXIT_FAILURE;
}
