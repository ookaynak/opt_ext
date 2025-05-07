import os
import pickle
import csv
import networkx as nx
import pandas as pd  # Add pandas import for save_dataframe_as_csv

def save_as_pkl(data, folder_path, name):  # Changed first arg name from 'dict'
    """Saves data to a pickle file."""
    pickle_path = os.path.join(folder_path, name)
    try:
        with open(pickle_path, "wb") as pickle_file:
            pickle.dump(data, pickle_file)
        print(f"Data saved to {pickle_path} using pickle")
    except Exception as e:
        print(f"ERROR: Failed to save pickle file {pickle_path}: {e}")

def save_dataframe_as_csv(df, folder_path, filename, index=True):
    """Saves a pandas DataFrame to a CSV file."""
    csv_path = os.path.join(folder_path, filename)
    try:
        df.to_csv(csv_path, index=index)
        print(f"DataFrame saved to {csv_path}")
    except Exception as e:
        print(f"ERROR: Failed to save DataFrame to CSV {csv_path}: {e}")

def save_as_csv(data_dict, folder_path, filename):
    """Saves a dictionary to a CSV file."""
    csv_path = os.path.join(folder_path, filename)
    try:
        with open(csv_path, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["Variable", "Value"])
            for name, value in data_dict.items():
                writer.writerow([name, value])
        print(f"CSV file saved to {csv_path}")
    except Exception as e:
        print(f"ERROR: Failed to save CSV file {csv_path}: {e}")

def save_as_graphml(graph, folder_path, filename):
    """Saves a NetworkX graph to a GraphML file."""
    graphml_path = os.path.join(folder_path, filename)
    try:
        nx.write_graphml(graph, graphml_path)
        print(f"GraphML file saved to {graphml_path}")
    except Exception as e:
        print(f"ERROR: Failed to save GraphML file {graphml_path}: {e}")

def load_pickle_as_dict(file_path):
    """Load a pickle file and return its content, with error handling."""
    if not os.path.isfile(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        return None
    try:
        with open(file_path, "rb") as file:
            data = pickle.load(file)
            return data
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except PermissionError:
        print(f"Error: Permission denied to read the file '{file_path}'.")
    except pickle.UnpicklingError:
        print(f"Error: The file '{file_path}' is not a valid pickle file or is corrupted.")
    except Exception as e:
        print(f"An unexpected error occurred while loading {file_path}: {e}")
    return None

def load_graphml(file_path):
    """Load a GraphML file and return it as a NetworkX graph, with error handling."""
    if not os.path.isfile(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        return None
    try:
        graph = nx.read_graphml(file_path)
        return graph
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except PermissionError:
        print(f"Error: Permission denied to read the file '{file_path}'.")
    except nx.NetworkXError as e:
        print(f"Error: The file '{file_path}' is not a valid GraphML file or is corrupted.")
        print(f"NetworkXError: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    return None

def get_link_speed(graph, sender, receiver):
    """
    Retrieves the link speed for a directed edge in the graph.

    Args:
        graph (networkx.Graph): The network graph.
        sender (str): The sender node.
        receiver (str): The receiver node.

    Returns:
        float: The link speed between the sender and receiver.
    """
    return graph[sender][receiver][str((sender, receiver))]
    
