from models.output_generator import OutputManager
from stream_dictionary_creator.stream_dict_creator import StreamDictCreator
from utils.helper import (
    load_graphml,
    load_pickle_as_dict,
    save_as_csv,
    save_as_graphml,
    save_as_pkl,
)
from utils.path_manager import PathManager
from models.batches.main import solve_with_batches, save_timing_info
from utils.memory_tracker import MemoryTracker  # Import the memory tracker

import os
import uuid
import shutil
import argparse
import time
from datetime import datetime
import traceback


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Run TSN Scheduling Pipeline")
    parser.add_argument('--input', type=str, help='Path to input directory',
                       default=None)  # Will default to data/input in main()
    parser.add_argument('--output', type=str, help='Path to output directory',
                       default=None)  # Will default to data/output in main()
    parser.add_argument('--config', type=str, help='Path to config file',
                       default=None)  # Will try input_dir/link_config.yaml by default
    parser.add_argument('--streams', type=int, help='Number of streams to process',
                       default=280)
    parser.add_argument('--batch-size', type=int, help='Batch size for processing',
                       default=10)
    parser.add_argument('--time-limit', type=int, help='Time limit for solver in seconds',
                       default=100)
    parser.add_argument('--k-paths', type=int, help='Number of paths per stream',
                       default=3)
    parser.add_argument('--highlight', type=int, help='Stream ID to highlight',
                       default=None)  # Default to stream 5, which should be scheduled
    parser.add_argument('--memory-interval', type=int, help='Memory sampling interval in seconds',
                       default=5)
    return parser.parse_args()


def create_batches(total_count, batch_size):
    """Create batches for optimization"""
    batches = []
    start = 0
    while start < total_count:
        end = min(start + batch_size, total_count)
        batches.append([x for x in range(start, end)])
        start = end
    return batches


def create_priority_batches(streams_df, total_count, batch_size, priority_column="priority"):
    """
    Create batches for optimization based on stream priorities.
    Higher priority streams (higher numerical values) are placed in earlier batches.
    
    Args:
        streams_df: DataFrame containing stream information with priority column
        total_count: Total number of streams
        batch_size: Maximum number of streams per batch
        priority_column: Column name for priority in the DataFrame (default: 'priority')
        
    Returns:
        List of batches, where each batch is a list of stream indices
    """
    batches = []
    
    # Check if priority column exists
    if streams_df is not None and priority_column in streams_df.columns:
        print("Creating batches based on stream priority (higher priority value = higher priority)")
        
        # Create a mapping of indices to priorities
        priorities = {}
        for idx, row in streams_df.iterrows():
            stream_idx = idx
            priority = row[priority_column]
            priorities[stream_idx] = priority
            
        # Sort stream indices by priority (HIGHER value = higher priority)
        sorted_indices = sorted(priorities.keys(), key=lambda x: priorities.get(x, 0), reverse=True)
        
        # Create batches based on priority order
        for i in range(0, len(sorted_indices), batch_size):
            batch = sorted_indices[i:i + batch_size]
            batches.append(batch)
            
        # Print priority distribution
        priority_counts = streams_df[priority_column].value_counts().sort_index()
        print(f"Priority distribution: {dict(priority_counts)}")
    else:
        print("No priority information found. Creating batches sequentially.")
        start = 0
        while start < total_count:
            end = min(start + batch_size, total_count)
            batches.append([x for x in range(start, end)])
            start = end
    
    return batches


def main():
    # Parse command line arguments
    args = parse_args()
    
    # Set up paths
    base_dir = os.path.dirname(__file__)
    data_dir = os.path.join(base_dir, "data")
    input_dir = args.input or os.path.join(data_dir, "input")
    
    # Create folder name with format: run_YYYYMMDD_HHMMSS_uuid-part
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uuid_part = str(uuid.uuid4())[:8]  # Take just the first 8 characters of the UUID
    folder_name = f"run_{timestamp}_{uuid_part}"
    
    output_dir = args.output or os.path.join(data_dir, "output", folder_name)

    # Print start information
    print("=== Starting TSN Scheduling Pipeline ===")
    start_time = datetime.now()
    print(f"Start time: {start_time}")
    path_manager = PathManager(input_dir=input_dir, output_dir=output_dir)
    
    print(f"Output folder: {path_manager.output_dir}")
    
    # Start memory tracking
    tracker = None
    try:
        tracker = MemoryTracker(output_folder=path_manager.memory_dir, interval=args.memory_interval)
        tracker.start()
    except Exception as e:
        print(f"WARNING: Failed to initialize memory tracker: {e}")
        # Continue without tracking
    
    streams_df = None
    
    try:
        # Copy input files, with special handling for streams.csv
        print("Copying input files...")
        for item in os.listdir(input_dir):
            s = os.path.join(path_manager.input_dir, item)
            d = os.path.join(path_manager.output_dir, item)
            
            # Special handling for streams.csv to limit the number of rows
            if item == "streams.csv" and args.streams is not None:
                try:
                    import pandas as pd
                    # Read the CSV file
                    streams_df = pd.read_csv(s)
                    original_count = len(streams_df)
                    
                    # Limit the number of rows
                    if args.streams < original_count:
                        print(f"Limiting streams.csv from {original_count} to {args.streams} rows")
                        limited_df = streams_df.iloc[:args.streams]
                        # Save the limited dataframe directly to the output file
                        limited_df.to_csv(d, index=False)
                        # Update the streams_df to use the limited version
                        streams_df = limited_df
                    else:
                        # Just copy the file as is
                        shutil.copy2(s, d)
                except Exception as e:
                    print(f"WARNING: Error processing streams.csv: {e}")
                    # Fall back to direct copy
                    shutil.copy2(s, d)
                    streams_df = None
            elif os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
                
        print("Input files copied.")
        
        # Set up config path
        config_path = args.config
        if not config_path:
            config_path = path_manager.link_config_input_dir

        # Create stream dictionary
        print(f"\n--- Creating Stream Dictionary (k_paths={args.k_paths}) ---")
        stream_dict_creator = StreamDictCreator(
            input_path=path_manager.input_dir,
            output_path=path_manager.output_dir,
            config_path=config_path,
            k_path_count=args.k_paths,
        )

        # Load all packets and graph data
        packets, graph_nx = stream_dict_creator.load_data()
        
        # Limit the number of packets based on args.streams
        original_packet_count = len(packets)
        if args.streams < original_packet_count:
            print(f"Limiting input streams from {original_packet_count} to {args.streams}")
            packets = packets[:args.streams]  # Take only the first args.streams packets
        
        # Create stream dictionary with the limited set of packets
        stream_dict = stream_dict_creator.populate_stream_dict(packets, graph_nx)
        save_as_graphml(graph_nx, path_manager.output_dir, "network.graphml")
        print(f"Stream dictionary created with {len(stream_dict)} streams")
        
        # Determine number of streams to process
        total_count = len(stream_dict)
        batch_size = args.batch_size
        print(f"Processing {total_count} streams in batches of {batch_size}")
        
        # Create batches based on priority if available
        batches = create_priority_batches(streams_df, total_count, batch_size)
        
        # Print batch information
        print(f"Created {len(batches)} batches:")
        for i, batch in enumerate(batches):
            if streams_df is not None and 'priority' in streams_df.columns:
                # Get priorities for this batch if we have that information
                batch_priorities = []
                for stream_idx in batch:
                    if stream_idx < len(streams_df):
                        priority = streams_df.iloc[stream_idx]['priority'] if 'priority' in streams_df.columns else '?'
                        batch_priorities.append(priority)
                    else:
                        batch_priorities.append('?')
                print(f"  Batch {i+1}: {len(batch)} streams, indices: {batch}, priorities: {batch_priorities}")
            else:
                print(f"  Batch {i+1}: {len(batch)} streams, indices: {batch}")
        
        # Run optimization
        print(f"\n--- Running Optimization (time_limit={args.time_limit} seconds) ---")
        (
            status,
            variables,
            variables_x,
            variables_y,
            variables_z,
            variables_a,
            timing_info,
        ) = solve_with_batches(
            stream_dict=stream_dict,
            output_path=path_manager.output_dir,
            batches=batches,
            time_limit=args.time_limit,
        )
        print(f"Optimization status: {status}")
        
        # Save timing information
        save_timing_info(timing_info, path_manager.output_dir)
        
        # Save results
        print("\n--- Saving Results ---")
        save_as_pkl(stream_dict, path_manager.output_dir, "stream_dict.pkl")
        save_as_pkl(variables_x, path_manager.output_dir, "variables_x.pkl")
        save_as_pkl(variables_y, path_manager.output_dir, "variables_y.pkl")
        save_as_pkl(variables_z, path_manager.output_dir, "variables_z.pkl")
        save_as_pkl(variables_a, path_manager.output_dir, "variables_a.pkl")
        print(f"Results saved.")
        
        # Generate output visualization
        print(f"\n--- Generating Output Visualization (highlighting stream {args.highlight}) ---")
        output_manager = OutputManager(path_manager)
        output_manager.process(highlight_stream_index=args.highlight)
            
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
    finally:
        # Stop memory tracking
        if tracker:
            try:
                tracker.stop()
                tracker.plot_usage(path_manager.memory_dir)
            except Exception as e:
                print(f"WARNING: Error stopping memory tracker: {e}")
        
        # Final summary
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"\n=== Pipeline Complete ===")
        print(f"Total execution time: {duration}")
        print(f"Results saved in folder: {folder_name}")
        print(f"Full path: {path_manager.output_dir}")


if __name__ == "__main__":
    main()
