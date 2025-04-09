# Check if a dataset argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <dataset>"
    exit 1
fi

dataset="$1"

gcloud storage rsync -r gs://tour_storage/data/$dataset data/$dataset

image_path=data/$dataset/images
echo "Image path is set to: $image_path"

colmap_intermediate_output_path=colmap_output/$dataset_$(date +%s)

# make a fresh output directory
mkdir -p $colmap_intermediate_output_path

# run colmap feature extractor
colmap feature_extractor \
    --database_path $colmap_intermediate_output_path/database.db \
    --image_path $image_path \
    --ImageReader.single_camera 1 \
    --ImageReader.camera_model OPENCV

# Run colmap sequential matcher
# colmap sequential_matcher \
colmap exhaustive_matcher \
    --database_path $colmap_intermediate_output_path/database.db \
    --SiftMatching.use_gpu 1

# Run colmap mapper
#TODO: Ceres for some reason is compiled with GPU support so it gets disabled. I wonder if there is an issue about that on colmap docs
colmap mapper \
    --database_path $colmap_intermediate_output_path/database.db \
    --image_path $image_path \
    --output_path $colmap_intermediate_output_path \
    --Mapper.ba_global_function_tolerance=1e-6

#TODO: For some reason I can't find this option    
# --Mapper.ba_global_function_tolerance 1e-6

sparse_output_path=data/$dataset/sparse_colmap/0
mkdir -p $sparse_output_path

# Run colmap bundle_adjuster
colmap bundle_adjuster \
    --input_path $colmap_intermediate_output_path/0 \
    --output_path $sparse_output_path \
    --BundleAdjustment.refine_principal_point 1

#TODO: Both of these don't work for some reason, so it's better to be specific i think
# I think it has to do with modal volumes, so it's better if we go into the unit itself
cd data
gcloud storage rsync -r . gs://tour_storage/data
cd ..