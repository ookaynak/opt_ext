# stream_dict_creator.py
import csv
import networkx as nx
import math
from typing import Dict, List, Tuple
from utils.path_calculator import k_shortest_paths
from utils.helper import load_graphml
import yaml


class StreamDictCreator:
    def __init__(self, input_path, output_path: str, config_path: str, k_path_count: int = 3):
        """
        Initialize StreamDictCreator with the path to the folder containing the required files.

        Args:
            input_path (str): Path to the folder containing the packet and graph files.
            output_path (str): Path to the folder where output files will be saved.
            config_path (str): Path to the YAML configuration file.
        """
        self.input_path = input_path
        self.output_path = output_path
        self.config_path = config_path
        self.streams_csv_path = f"{self.input_path}/streams.csv"
        self.graph_ml_path = f"{self.input_path}/network.graphml"
        self.config = self.load_config()
        self.k_path_count = k_path_count

    def load_config(self):
        """
        Load the YAML configuration file.

        Returns:
            dict: The configuration dictionary.
        """
        with open(self.config_path, "r") as file:
            return yaml.safe_load(file)

    def load_data(self):
        """
        Loads the streams and graph data from the files specified during initialization.

        Returns:
            tuple: A tuple containing streams (list) and graph (networkx graph).
        """

        def load_streams_from_csv(filename: str) -> List[Dict[str, int]]:
            """
            Loads streams from a CSV file into a list of dictionaries.

            Args:
                filename (str): The name of the file to load the streams from.

            Returns:
                List[Dict[str, int]]: A list of stream dictionaries loaded from the CSV file.
            """
            streams = []
            with open(filename, mode="r") as file:
                csv_reader = csv.DictReader(file)
                for row in csv_reader:
                    # Convert appropriate fields to integers
                    row["src"] = str(row["src"])
                    row["dst"] = str(row["dst"])
                    row["packet_size"] = int(row["packet_size"])
                    row["period"] = int(row["period"])
                    # Add new fields with proper type conversion
                    if "max_latency" in row:
                        row["max_latency"] = int(row["max_latency"])
                    if "priority" in row:
                        row["priority"] = int(row["priority"])
                    if "gamma" in row:
                        row["gamma"] = float(row["gamma"])  # Convert gamma to float to handle decimal values
                    if "max_jitter" in row:
                        row["max_jitter"] = int(row["max_jitter"])  # Add max_jitter field
                    streams.append(row)

            return streams

        streams = load_streams_from_csv(self.streams_csv_path)
        graph_nx = load_graphml(self.graph_ml_path)
        return streams, graph_nx

    def get_link_type(self, graph, sender, receiver):
        """
        Retrieves the link type for a directed edge in the graph.
        Handles nodes with port identifiers (e.g., "SW5#1").

        Args:
            graph (networkx.Graph): The network graph.
            sender (str): The sender node.
            receiver (str): The receiver node.

        Returns:
            int: The link type between the sender and receiver.
        """
        # Remove any port identifier (part after #)
        sender_base = sender.split('#')[0] if '#' in sender else sender
        receiver_base = receiver.split('#')[0] if '#' in receiver else receiver
        
        # Get the link type using the base node names
        return graph[sender_base][receiver_base]["link_type"]

    def calculate_transmission_time(
        self, byte_size, link_type, processing_time=10, propagation_time=10
    ):
        """
        Calculates the transmission time for frames, considering frame splitting if needed.

        Args:
            byte_size (int): The packet size in bytes.
            link_type (int): The link type.
            processing_time (int, optional): Processing time in ms. Default is 10ms.
            propagation_time (int, optional): Propagation time in ms. Default is 10ms.

        Returns:
            Tuple[Dict[int, float], Dict[int, float]]: A tuple containing two dictionaries:
                - times_dict: A dictionary with frame index as keys and transmission times as values.
                - deviations_dict: A dictionary with frame index as keys and deviations as values.
        """
        remaining_size = byte_size  # Initialize remaining_size here
        config = self.config["link_types"][link_type]

        if link_type == "0":
            link_speed = config["best_case_speed"]
            num_frames = math.ceil(byte_size / 1500)
            frame_size = math.ceil(byte_size / num_frames)
            times_dict = {
                frame_index: math.ceil((frame_size * 8) / link_speed)
                + config["processing_time"]
                + config["propagation_time"]
                for frame_index in range(num_frames)
            }
            deviations_dict = {
                frame_index: math.ceil((frame_size * 8) / config["worst_case_speed"])
                + config["processing_time"]
                + config["propagation_time"]
                - times_dict[frame_index]
                for frame_index in range(num_frames)
            }
        else:
            available_sizes = sorted(map(int, config["packet_sizes"].keys()), reverse=True)
            times_dict = {}
            deviations_dict = {}
            frame_index = 0
            while remaining_size > 0:
                for size in available_sizes:
                    if size <= remaining_size:
                        # Convert size back to string for dictionary lookup
                        size_key = str(size)
                        times = config["packet_sizes"][size_key]  # Use string key
                        times_dict[frame_index] = times["best_case_time"]
                        # Ensure deviation calculation uses the correct base time
                        deviations_dict[frame_index] = times["worst_case_time"] - times_dict[frame_index]
                        remaining_size -= size
                        frame_index += 1
                        break

        return times_dict, deviations_dict

    def maximize_sum(self, num_frames, packet_data, current_port, next_port):
        """
        Helper function to maximize the sum for calculating ns value.

        Args:
            num_frames (int): Number of frames.
            packet_data (dict): The path data for the packet.
            current_port (str): The current port.
            next_port (str): The next port.

        Returns:
            float: The maximum sum value.
        """
        max_value = float("-inf")
        for i in range(1, num_frames):
            summation = (
                sum(packet_data["times"][current_port][k] for k in range(i + 1))
                + min(
                    packet_data["gamma"][current_port]
                    * sum(packet_data["deviations"][current_port].values()),
                    sum(
                        packet_data["deviations"][current_port][k]
                        for k in range(i + 1)
                    ),
                )
                - sum(packet_data["times"][next_port][k] for k in range(i))
                - min(
                    packet_data["gamma"][next_port]
                    * sum(packet_data["deviations"][next_port].values()),
                    sum(
                        packet_data["deviations"][current_port][k] for k in range(i)
                    ),
                )
            )
            max_value = max(max_value, summation)
        return max_value

    def calculate_ns(self, packet_path_data, current_port, port_index):
        """
        Calculates the ns value for a packet along a path segment.

        Args:
            packet_path_data (dict): The path data for the packet.
            current_port (str): The current port.
            port_index (int): The index of the current port in the path.

        Returns:
            int: The calculated ns value.
        """
        next_port = packet_path_data["ports"][port_index + 1]
        if len(packet_path_data["times"][current_port]) > 1:
            return math.ceil(
                max(
                    packet_path_data["times"][current_port][0]
                    + min(
                        packet_path_data["gamma"][current_port]
                        * sum(packet_path_data["deviations"][current_port].values()),
                        packet_path_data["deviations"][current_port][0],
                    ),
                    self.maximize_sum(
                        len(packet_path_data["times"][current_port]),
                        packet_path_data,
                        current_port,
                        next_port,
                    ),
                )
            )
        else:
            return math.ceil(
                packet_path_data["times"][current_port][0]
                + packet_path_data["gamma"][current_port]
                * sum(packet_path_data["deviations"][current_port].values())
            )

    def populate_stream_dict(self, streams, graph_nx):
        """
        Constructs a stream dictionary with computed paths, times, deviations, and other data.
        For links of configurable types, creates multiple parallel paths with different port identifiers.
        The number of parallel paths is determined from the configuration file.

        Args:
            streams (list): The list of packet data.
            graph_nx (networkx.Graph): The graph object representing the network.

        Returns:
            dict: A dictionary with streams and path-related information.
        """
        stream_dict = {}
        
        for packet_idx, packet in enumerate(streams):
            stream_dict[packet_idx] = {}
            path_counter = 0
            
            # Get the k shortest paths
            shortest_paths = k_shortest_paths(
                G=graph_nx, source=packet["src"], target=packet["dst"], k=self.k_path_count
            )
            
            for base_path_idx, base_path in enumerate(shortest_paths):
                # Check which links in the path need multiple parallel paths
                link_parallel_paths = {}
                
                for i, port in enumerate(base_path):
                    sender, receiver = port
                    link_type = self.get_link_type(graph=graph_nx, sender=sender, receiver=receiver)
                    # Get number of parallel paths from config
                    num_parallel = self.config["link_types"][link_type].get("parallel_paths", 1)
                    if num_parallel > 1:
                        link_parallel_paths[(i, port)] = (link_type, num_parallel)
                
                if link_parallel_paths:
                    # Calculate total number of path combinations based on parallel links
                    max_duplicates = max(paths for _, paths in link_parallel_paths.values())
                    
                    for duplicate_idx in range(max_duplicates):
                        # Create a modified path with port identifiers
                        modified_path = []
                        for i, port in enumerate(base_path):
                            sender, receiver = port
                            link_type = self.get_link_type(graph=graph_nx, sender=sender, receiver=receiver)
                            num_parallel = self.config["link_types"][link_type].get("parallel_paths", 1)
                            
                            if num_parallel > 1:
                                # Use modulo to distribute across available parallel paths
                                path_idx = duplicate_idx % num_parallel + 1
                                # Add port identifier to both nodes
                                modified_port = (f"{sender}#{path_idx}", f"{receiver}#{path_idx}")
                            else:
                                modified_port = port
                                
                            modified_path.append(modified_port)
                        
                        # Process the modified path
                        path_data = self._process_path(packet, modified_path, graph_nx)
                        stream_dict[packet_idx][path_counter] = path_data
                        path_counter += 1
                else:
                    # No parallel links needed, process the original path
                    path_data = self._process_path(packet, base_path, graph_nx)
                    stream_dict[packet_idx][path_counter] = path_data
                    path_counter += 1
                    
        return stream_dict

    def _process_path(self, packet, path, graph_nx):
        """
        Process a single path to generate path data including times, deviations, etc.
        
        Args:
            packet (dict): Packet information
            path (list): Path as a list of (sender, receiver) pairs
            graph_nx (networkx.Graph): Network graph
            
        Returns:
            dict: Path data including times, deviations, etc.
        """
        path_data = {
            "ports": path,
            "period": int(packet["period"]),
            "packet_size": int(packet["packet_size"]),
            "times": {},
            "deviations": {},
            "gamma": {},
            "bp": {},
            "ns": {},
        }
        
        # Add new fields if they exist in the packet data
        if "max_latency" in packet:
            path_data["max_latency"] = int(packet["max_latency"])
        if "priority" in packet:
            path_data["priority"] = int(packet["priority"])
        if "max_jitter" in packet:
            path_data["max_jitter"] = int(packet["max_jitter"])  # Add max_jitter to path data
        
        # Get gamma from packet data or use default value of 1
        default_gamma = packet.get("gamma", 1)
        
        for port in path:
            # Extract the base node names without port identifiers for graph lookup
            sender_base = port[0].split('#')[0] if '#' in port[0] else port[0]
            receiver_base = port[1].split('#')[0] if '#' in port[1] else port[1]
            
            # Get link type using the base node names
            link_speed = self.get_link_type(
                graph=graph_nx, sender=sender_base, receiver=receiver_base
            )
            
            # Calculate transmission times using the modified port names
            path_data["times"][port], path_data["deviations"][port] = (
                self.calculate_transmission_time(
                    path_data["packet_size"], link_speed
                )
            )
            
            # Use the gamma from the packet data or default
            path_data["gamma"][port] = default_gamma
        
        for port_index, port in enumerate(path[:-1]):
            path_data["ns"][port] = self.calculate_ns(
                path_data, port, port_index
            )
            # Disable bp calculation for now
            # path_data["bp"][port] = (
            #     path_data["ns"][port] - path_data["times"][port][0]
            # )
            path_data["bp"][port] = 0
        
        return path_data
