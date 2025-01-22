#!/usr/bin/env python3
import argparse
import csv
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta

try:
    import serial
except ImportError:
    print("pyserial is not installed.")
    sys.exit(1)

# Argument parsing
parser = argparse.ArgumentParser(description="Datalogger and configuration tool for Dragino LHT65N-E5.")
parser.add_argument("-E", "--export", metavar="NUM", nargs='?', const=100, type=int, help="Export the last NUM datalogger entries to a CSV file and exit. Default is 100 if not specified.")
args = parser.parse_args()

global ser  # Declare `ser` as a global variable

def graceful_exit(signum=None, frame=None):
    print("\nExiting…")
    sys.exit(0)

# Handle Ctrl+C or other termination signals gracefully
signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)

def check_file_and_get_action(filename):
    full_path = os.path.join("data", filename)
    if os.path.exists(full_path):
        action = input(f">_ File 'data/{filename}' already exists. [O]verwrite, [A]ppend, or [C]ancel (default: C)? ").lower() or "C"
        if action == 'o':
            return 'overwrite'
        elif action == 'a':
            return 'append'
        else:
            return 'cancel'
    else:
        return 'create'

import os

def export_to_csv(datalogger_entries, filename, num_entries=None, action=None):
    # Ensure the directory exists (create it if it doesn't)
    os.makedirs("data", exist_ok=True)
    full_path = os.path.join("data", filename)
    
    # Check for file existence and get the action (overwrite, append, cancel, create)
    if action is None:
        action = check_file_and_get_action(full_path)

    mode = 'w' if action == 'overwrite' or action == 'create' else 'a'
    header = "export_row,date,time,dragino_var,bat_voltage,temperature,humidity,light\n"
    processed_entries = process_datalogger_entries(datalogger_entries)
    
    with open(full_path, mode) as f:
        if f.tell() == 0 or action in ['overwrite', 'create']:
            f.write(header)
        for entry in processed_entries:
            f.write(f"{entry}\n")

    print("\033[K", end="")  # Clear the line before printing the final message
    print(f"Data {'saved' if mode == 'w' else 'appended'} to {full_path}")

def process_datalogger_entries(entries):
    processed_entries = []
    for entry in entries[:-1]:  # Skip the last lines
        parts = entry.split(' ')
        processed_parts = []
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                processed_parts.append(key_value[1].strip())
            else:
                processed_parts.append(part.strip())
        processed_entries.append(','.join(processed_parts))
    return processed_entries
    
def send_password(ser, password="123456", answer_wait_time=0.1, next_command_wait_time=0.5):
    print(f"\nSending password: {password}")
    ser.write((password + '\r\n').encode())
    time.sleep(answer_wait_time)

    responses = []
    # Collect responses for a brief period
    start_time = time.time()
    while time.time() - start_time < answer_wait_time:
        if ser.in_waiting:
            response = ser.readline().decode().strip()
            responses.append(response)

    # Find the specific response containing "Password"
    password_response = next((resp for resp in responses if "Password" in resp), None)

    if password_response:
        print("Received:", password_response)
    else:
        print("Device was already unlocked.")

    time.sleep(next_command_wait_time)  # Wait before sending the next command
    
def send_command(ser, command, post_wait_time=0.1, quiet=False):
    if not quiet:
        print(f"Sending: {command}")
    ser.write((command + '\r\n').encode())
    ser.flushInput()  # Clear the buffer before receiving new data.

    responses = []
    buffer = ''
    last_data_time = time.time()

    while True:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            buffer += data
            last_data_time = time.time()

            while '\r\n' in buffer:
                line, buffer = buffer.split('\r\n', 1)
                if line:
                    responses.append(line)

        elif time.time() - last_data_time >= post_wait_time:
            if buffer.strip():
                responses.append(buffer.strip())
            break
        else:
            time.sleep(0.05)

    # Process the responses to filter out unwanted messages
    processed_responses = []
    for response in responses:
        if response.startswith('Start') or (response == 'OK' and len(processed_responses) > 0):
            continue  # Skip 'Start' messages and 'OK' if it's not the only message
        processed_responses.append(response)

    # Modify responses if quiet=True
    if processed_responses:
        if quiet:
            # Strip the first character if it's a space and join without adding a newline at the start
            stripped_responses = [resp[1:] if resp.startswith(" ") else resp for resp in processed_responses]
            print("".join(stripped_responses), end="")
        else:
            print("Received:", "\n".join(processed_responses))
    else:
        if not quiet:
            print("No response")
    return processed_responses
        
def show_current_values(ser):
    print("\nCurrent readings:")
    ser.write(("AT+DADDR=?" + '\r\n').encode())
    time.sleep(0.1)
    device_address = ser.readline().decode().strip()
    print(f"Device address = {device_address}")
    eui = ''.join(send_command(ser, "AT+DEUI=?", 0.2, quiet=True))
    print("\033[1A")
    print(f"Device EUI = {eui.replace(' ', '')}", end='\r', flush=True)
    print(f"\nInterval = ", end="")
    send_command(ser, "AT+TDC=?", 0.2, quiet=True)
    print("ms\n", end="")
    send_command(ser, f"AT+GETSENSORVALUE=0", 0.2, quiet=True)
    print("\033[2A")
    send_command(ser, f"AT+TIMESTAMP=?", quiet=True)
    return device_address

def show_logger(ser):
    # Prompt for number of datalogger pages to showf
    entries = input("\n>_ Enter a number of datalogger entries to print (default: 10): ") or "10"
    print("")
    send_command(ser, f"AT+PLDTA={entries}", int(entries) / 400)
    
def fetch_logger_entries(ser, entries):
    logger_data = []
    command = f"AT+PLDTA={entries}"
    ser.write((command + '\r\n').encode())

    message = f"Fetching the last {entries} datalogger entries..."
    print(message, end="", flush=True)  # Print the initial message without a newline

    start_time = time.time()  # Record the start time
    times = deque(maxlen=50)  # Store times for the last 50 entries to calculate a moving average
    smoothed_eta = None  # Initialize smoothed ETA

    warmup_phase = entries // 10  # Warm-up phase is 10% of total entries

    last_length = 0  # Track the length of the previous message for clearing

    for line_num in range(entries):
        entry_start = time.time()  # Record the time at the start of processing this line

        # Read each line and append it to logger_data
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            logger_data.append(line)
        else:
            time.sleep(0.05)  # Allow time for data to arrive

        # Record the time for this entry
        times.append(time.time() - entry_start)

        # Update and display progress and ETA
        progress = ((line_num + 1) / entries) * 100

        if line_num + 1 > warmup_phase:  # Start showing ETA after the warm-up phase
            # Use a combined moving and cumulative average for ETA
            cumulative_avg_time = (time.time() - start_time) / (line_num + 1)
            smoothed_avg_time = sum(times) / len(times)
            average_time_per_entry = (cumulative_avg_time + smoothed_avg_time) / 2

            # Calculate remaining time and smooth ETA
            remaining_time = average_time_per_entry * (entries - (line_num + 1))
            if smoothed_eta is None:
                smoothed_eta = remaining_time  # Initialize smoothed ETA
            else:
                # Apply a smoothing factor (e.g., 0.9 for slow adjustments)
                smoothing_factor = 0.9
                smoothed_eta = smoothing_factor * smoothed_eta + (1 - smoothing_factor) * remaining_time

            # Format remaining time into minutes and seconds
            remaining_minutes, remaining_seconds = divmod(int(smoothed_eta), 60)

            output = f"{message} [{progress:.2f}% complete, ETA: {remaining_minutes}m {remaining_seconds}s]"
        else:
            # Show progress with "computing ETA" during the warm-up phase
            output = f"{message} [{progress:.2f}% complete, computing ETA…]"

        # Clear previous message by overwriting with spaces if shorter
        sys.stdout.write("\r" + output + " " * (last_length - len(output)))
        sys.stdout.flush()

        last_length = len(output)  # Update the length of the current message

    print("\n\033[K", end="")  # Clear the line after completion
    
    # Process the logger data to remove unwanted portions (trimming logic)
    trimmed_logger_data = []
    for item in logger_data:
        last_occurrence_index = item.rfind('\n\r') + 2  # +2 to move past '\n\r'
        trimmed_logger_data.append(item[last_occurrence_index:])

    return trimmed_logger_data

def read_boot_response(ser, password, keyword="Dragino", lines_after_keyword=5  ):
    print("\n>_ Hold 'ACT' until green blinking to start logging immediately, or press Enter to postpone the mission.")

    boot_responses = []
    user_input = [False]  # A flag to track user's choice to skip boot detection

    def accumulate_responses():
        nonlocal user_input
        lines_captured = 0
        while lines_captured <= lines_after_keyword and not user_input[0]:
            if ser.in_waiting:
                response = ser.readline().decode().strip()
                if response:
                    if keyword in response or lines_captured > 0:
                        boot_responses.append(response)
                        lines_captured += 1
            else:
                time.sleep(0.1)

        if boot_responses:
            print("\nDevice booting…\n" + "\n".join(boot_responses))
            print("\nMaking initial measurement…\n")

    def listen_for_enter():
        input()  # Blocking call until Enter is pressed
        user_input[0] = True  # Update the flag to indicate user action

    # Start threads for accumulating responses and listening for Enter key
    threading.Thread(target=accumulate_responses, daemon=True).start()
    threading.Thread(target=listen_for_enter, daemon=True).start()

    # Wait for either boot detection completion or user to press Enter
    while not user_input[0] and len(boot_responses) <= lines_after_keyword:
        time.sleep(0.1)

    if boot_responses:
        time.sleep(6)
        ser.write((password + '\r\n').encode()) # Unlock after boot
        time.sleep(3)  # Give some time for the device to process the command
            
def main(serial_device='/dev/ttyUSB0', baud_rate=9600):
    with serial.Serial(serial_device, baud_rate, timeout=1) as ser:
        password = input(">_ Enter password to unlock device and read values (default: 123456): ") or "123456"

        send_password(ser, password)

        device_address = show_current_values(ser)



       # Check if the export flag was provided
        if args.export is not None:
            # If args.export has a value (including the default const value), it means -E was used
            # Now check if it was provided without a specific number (args.export would be 100, the const value)
            if args.export == 100:
                # Prompt the user to confirm or enter a new number for NUM
                user_input = input("\n>_ Enter the number of datalogger entries to export (default: 100): ")
                if user_input:  # If the user entered a value
                    try:
                        entries_to_export = int(user_input)
                        spacer = ""
                    except ValueError:
                        print("Invalid number. Using default of 100 entries.")
                        entries_to_export = 100
                        spacer = ""
                else:
                    entries_to_export = 100  # Use default if the user pressed Enter without typing a number
                    spacer = ""
            else:
                # args.export is a user-specified value, so use it directly
                entries_to_export = args.export
                spacer = "\n"

            default_file = device_address + '.csv'
            filename = input(f"{spacer}>_ Enter filename for CSV export (default: {default_file}): ") or default_file
            action = check_file_and_get_action(filename)

            if action == 'cancel':
                print("Export cancelled.")
                sys.exit(0)

            trimmed_logger_data = fetch_logger_entries(ser, entries=entries_to_export)
            export_to_csv(trimmed_logger_data, filename, num_entries=int(entries_to_export), action=action)
            sys.exit(0)
        else:
            show_logger(ser)

        interval = input("\n>_ Press C-c to exit without reconfiguring, or set a logging interval in seconds to continue (default: 3600): ") or "3600"
        interval_milliseconds = int(interval) * 1000

        print("\nSetting device parameters (see script comments for details):")
        unix_time_now = int(time.time())
        commands = [
            f"AT+TIMESTAMP={unix_time_now}",  # Synchronize clock   
            "AT+TXP=5",                       # 5 means miniamal transmit power
            "AT+NJM=0",                       # Set to ABP to avoid searching network  
            f"AT+TDC={interval_milliseconds}" # Set interval  
        ]

        for cmd in commands:
            send_command(ser, cmd)

        show_current_values(ser)
        read_boot_response(ser, password, keyword="Dragino", lines_after_keyword=5)

        print("Data logger overview (first and last values):")
        time.sleep(0.5)
        commands = [
            "AT+PDTA=1,1", # First logger page
            "AT+PLDTA=7"   # Last 7 logger entries
        ]
        for cmd in commands:
            send_command(ser, cmd)

        print(f"\n---   \n\nThe LHT65N-E5 will now log data every {interval}s, starting when you long press(ed) ACT until green blinking. To stop an ongoing mission, press short press ACT 5 times. A long press until green blinking will restart a mission from that time.")

if __name__ == "__main__":
    # Prompt user for serial device and baud rate
    if args.export is None:
        message = "This script will unlock a Dragino LHT65N-E5 to show log data and, optionally, resynchronize the clock and reconfigure the recording interval. A device configured in advance for a future mission should be kept in deep sleep (5 short presses on ACT if a mission was already running) and reactivated when relevant with a long press on ACT (e.g., at a round hour)."
    else:
        message = "Export mode: this action will unlock a Dragino LHT65N-E5 and export its datalogger entries into a csv file."
        
    print(f"""\033[34m{message}\033[0m

\033[90mThe operation requires a FTDI adapter and a Dragino E2 cable wired as follows:
- E2 white (port 4) to FTDI RX
- E2 green (port 5) to FTDI TX
- E2 black (port 9) to FTDI GND
- E2 cable plugged on the external sensor port of the LHT65N-E5\033[0m
""")
    serial_device = input(">_ Enter serial device (default: /dev/ttyUSB0): ") or '/dev/ttyUSB0'
    baud_rate = input(">_ Enter baud rate (default: 9600): ") or '9600'
    baud_rate = int(baud_rate)
    main(serial_device, baud_rate)
