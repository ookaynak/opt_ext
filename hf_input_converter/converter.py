import networkx as nx
import matplotlib.pyplot as plt
import os
import pandas as pd

def print_graph_info(G, name):
    """Prints basic information about the graph."""
    print(f"\n--- Info for {name} ---")
    print(f"Nodes ({G.number_of_nodes()}): {list(G.nodes())}")
    print(f"Edges ({G.number_of_edges()}):")
    for u, v, data in G.edges(data=True):
        # Ensure data is represented concisely for printing
        data_str = ", ".join([f"{k}: {v}" for k, v in data.items()])
        print(f"  ({u}) -> ({v}) | Data: {{{data_str}}}")

def draw_graph(G, file_path, title, show_all_edge_data=False, edge_label_key=None):
    """Draws the graph and saves it to a file."""
    plt.figure(figsize=(12, 10))
    try:
        pos = nx.spring_layout(G, k=0.5, iterations=50) # k adjusts spacing, iterations for layout stability
    except Exception: # Fallback if spring_layout fails for some reason (e.g. disconnected graph)
        pos = nx.kamada_kawai_layout(G)

    nx.draw_networkx_nodes(G, pos, node_size=500, alpha=0.8)
    nx.draw_networkx_edges(G, pos, width=1.5, alpha=0.7, arrowsize=15)
    nx.draw_networkx_labels(G, pos, font_size=8)

    edge_labels_to_draw = {}
    if show_all_edge_data:
        for u, v, data_dict in G.edges(data=True):
            edge_labels_to_draw[(u,v)] = '\n'.join(f'{k}: {v}' for k, v in data_dict.items() if v is not None)
    elif edge_label_key:
        for u, v, data_dict in G.edges(data=True):
            edge_labels_to_draw[(u,v)] = str(data_dict.get(edge_label_key, ''))

    if edge_labels_to_draw:
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels_to_draw, font_size=7, bbox=dict(alpha=0.1, boxstyle="round,pad=0.1"))

    plt.title(title, fontsize=15)
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(file_path)
    print(f"Graph drawing saved to {file_path}")
    plt.close() # Close the figure to free memory

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    graph_input_path = os.path.join(script_dir, 'data', 'input', 'graph.graphml')
    flows_input_path = os.path.join(script_dir, 'data', 'input', 'flows.csv')
    
    output_dir = os.path.join(script_dir, 'data', 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    output_original_graph_path = os.path.join(output_dir, 'original_input_graph.png')
    output_processed_graph_path = os.path.join(output_dir, 'network.png') # For the drawing
    output_streams_csv_path = os.path.join(output_dir, 'streams.csv')
    output_processed_graphml_path = os.path.join(output_dir, 'network.graphml') # For the GraphML output

    if not os.path.exists(graph_input_path):
        print(f"Error: GraphML file not found at {graph_input_path}")
        return
    if not os.path.exists(flows_input_path):
        print(f"Error: Flows CSV file not found at {flows_input_path}")
        return

    try:
        # Load original graph
        original_graph = nx.read_graphml(graph_input_path)
        print(f"Successfully read graph from {graph_input_path}")

        # Print and draw original graph
        print_graph_info(original_graph, "Original Graph")
        draw_graph(original_graph, output_original_graph_path, "Original Input Graph", show_all_edge_data=True)

        # Load flows data
        flows_df = pd.read_csv(flows_input_path)
        ed_node_original_ids = set(flows_df['Src'].astype(str).unique()) | \
                               set(flows_df['Dst'].astype(str).unique())
        print(f"\nNodes identified from flows.csv (Src/Dst) as ED type: {ed_node_original_ids}")

        # Create a new graph for processing
        # We will modify attributes directly on this copy
        processed_graph = original_graph.copy()

        # --- Edge Attribute Processing for processed_graph ---
        print("\nProcessing edge attributes for graph...")
        for u, v, data in processed_graph.edges(data=True):
            edge_rate_value = None
            if 'link_type' in data:
                edge_rate_value = data['link_type']
            elif 'rate' in data:
                edge_rate_value = data['rate']
            elif 'link_rate' in data:
                edge_rate_value = data['link_rate']
            else:
                # Default if no rate attribute found, matching example's '0' or '1' values
                # Or use "N/A" if that's more appropriate for your data
                edge_rate_value = "0" 
            
            # Clear existing attributes and set the new 'link_type'
            current_keys = list(data.keys())
            for key in current_keys:
                del data[key]
            data['link_type'] = str(0)
            # This 'link_type' will also be used for drawing if specified

        # --- Node Renaming ---
        print("\nProcessing node renaming for graph...")
        node_mapping = {}
        # Assuming node IDs in graph.graphml that are in flows.csv are simple strings like "0", "1", etc.
        for node_id_obj in processed_graph.nodes():
            original_node_str = str(node_id_obj) 
            if original_node_str in ed_node_original_ids:
                node_mapping[node_id_obj] = f"0-ED{original_node_str}" # No hyphen before number
            else:
                node_mapping[node_id_obj] = f"0-SW{original_node_str}" # No hyphen before number
        
        final_graph = nx.relabel_nodes(processed_graph, node_mapping, copy=True)
        print(f"Node mapping applied: {node_mapping}")

        # --- Node Attribute Processing for final_graph ---
        print("\nProcessing node attributes for final_graph...")
        for node_id, data in final_graph.nodes(data=True):
            # Clear any attributes copied from original_graph/processed_graph
            current_keys = list(data.keys())
            for key in current_keys:
                del data[key]
            
            # Set new attributes as per the example structure
            data['subnet'] = '0' # Example uses '0' for all nodes
            if str(node_id).startswith("0-ED"):
                data['type'] = 'ED'
            elif str(node_id).startswith("0-SW"):
                data['type'] = 'SW'
            # Note: This logic doesn't create 'WN' or 'WED' types from the example.
            # It categorizes all non-ED nodes (not in flows.csv) as SW.

        # Print and draw processed graph
        print_graph_info(final_graph, "Processed Graph (for network.png and network.graphml)")
        # Draw using the 'link_type' attribute for edge labels
        draw_graph(final_graph, output_processed_graph_path, "Processed Network Graph", edge_label_key='link_type')
        
        # Save the processed graph to GraphML
        nx.write_graphml(final_graph, output_processed_graphml_path, infer_numeric_types=True)
        print(f"Processed graph saved to {output_processed_graphml_path}")

        # --- Convert flows.csv to streams.csv format ---
        print(f"\nConverting {flows_input_path} to {output_streams_csv_path} format...")
        streams_df = flows_df.copy()

        streams_df.rename(columns={
            'Flow ID': 'index',
            'Src': 'src',
            'Dst': 'dst',
            'Period': 'period',
            'Jitter': 'max_jitter',
            'Payload': 'packet_size',
            'Path Length': 'path_length' 
        }, inplace=True)

        if 'index' in streams_df.columns:
            streams_df['index'] = streams_df['index'].astype(str).str.replace('F', '').astype(int)

        # Use the new node naming convention for src/dst in streams.csv
        if 'src' in streams_df.columns:
            streams_df['src'] = "0-ED" + streams_df['src'].astype(str) # No hyphen before number
        if 'dst' in streams_df.columns:
            streams_df['dst'] = "0-ED" + streams_df['dst'].astype(str) # No hyphen before number

        if 'period' in streams_df.columns:
            streams_df['max_latency'] = streams_df['period']
        else:
            streams_df['max_latency'] = None 

        streams_df['priority'] = 1
        streams_df['gamma'] = 1
        
        streams_df.columns = [col.lower() for col in streams_df.columns]

        desired_columns = [
            'index', 'src', 'dst', 'packet_size', 'period', 
            'max_latency', 'priority', 'gamma', 'max_jitter'
        ]
        if 'path_length' in streams_df.columns:
            desired_columns.append('path_length')
        else:
            print("Warning: 'path_length' column not found after renaming. It will not be in streams.csv.")

        final_streams_columns = [col for col in desired_columns if col in streams_df.columns]
        streams_df = streams_df[final_streams_columns]
        
        streams_df.to_csv(output_streams_csv_path, index=False)
        print(f"Successfully converted flows and saved to {output_streams_csv_path}")
        print("Columns in generated streams.csv:", streams_df.columns.tolist())

        print("\nProcessing complete.")

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()