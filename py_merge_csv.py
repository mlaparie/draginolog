#!/usr/bin/env python3
import csv
import datetime
import os

# Paths setup
device_addresses_path = 'device_addresses.csv'
data_dir = './data'
output_filename = f"py-merged_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
output_path = os.path.join(data_dir, output_filename)

# Ensure the output file doesn't exist from a previous run
if os.path.exists(output_path):
    os.remove(output_path)

device_headers = []

# Open the output file for writing
with open(output_path, 'w', newline='') as outfile:
    writer = csv.writer(outfile)
    
    # Process the device_addresses.csv
    with open(device_addresses_path, 'r') as infile:
        reader = csv.reader(infile)
        main_headers = next(reader)  # Skip header
        
        for row in reader:
            id, device_address = row
            device_file_path = os.path.join(data_dir, f"{device_address}.csv")
            
            if os.path.exists(device_file_path):
                with open(device_file_path, 'r') as device_file:
                    device_reader = csv.reader(device_file)
                    if not device_headers:
                        device_headers = next(device_reader)  # Read device file header
                        writer.writerow(main_headers + device_headers)
                    else:
                        next(device_reader)  # Skip device file header
                        
                    for device_row in device_reader:
                        writer.writerow([id, device_address] + device_row)

print(f"Merged file created: {output_path}")
