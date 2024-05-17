#!/usr/bin/env bash

# Navigate to the script directory
cd "$(dirname "$0")"

# Define variables
device_addresses="device_addresses.csv"
data_dir="./data"
datetime=$(date +"%Y%m%d_%H%M%S")
output="${data_dir}/sh-merged_${datetime}.csv"

# Create the output file and ensure it's initially empty
: > "$output"

# First, process the device_addresses.csv to get the headers
while IFS=, read -r id device_address; do
    if [ "$id" != "id" ]; then  # Skip the header of device_addresses.csv
        file="${data_dir}/${device_address}.csv"
        if [ -f "$file" ]; then
            if [ ! -s "$output" ]; then  # If output file is empty, extract and write headers
                head -1 "$file" | awk -v id="$id" -v da="$device_address" 'BEGIN{OFS=","}{print "id","device_address",$0}' > "$output"
            fi
            # Append data to output, skipping the header of the device file
            tail -n +2 "$file" | awk -v id="$id" -v da="$device_address" 'BEGIN{FS=",";OFS=","}{print id,da,$0}' >> "$output"
        fi
    fi
done < "$device_addresses"

echo "Merged file created: $output"
