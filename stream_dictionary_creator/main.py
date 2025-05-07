from stream_dictionary_creator.stream_dict_creator import StreamDictCreator
from utils.helper import save_as_graphml, save_as_pkl
import os
import uuid
import shutil

def main():
    base_dir = os.path.dirname(__file__)  # Gets the directory of the current script
    input_dir = os.path.join(base_dir, "data", "input")
    output_dir = os.path.join(base_dir, "data", "output")

    # Create a UUID folder under the output directory
    folder_name = str(uuid.uuid4())
    output_folder = os.path.join(output_dir, folder_name)
    os.makedirs(output_folder, exist_ok=True)

    # Copy everything from the input folder to the output folder
    for item in os.listdir(input_dir):
        s = os.path.join(input_dir, item)
        d = os.path.join(output_folder, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    # Get path to link_config.yaml
    config_path = os.path.join(base_dir, "data", "link_config.yaml")
    
    # Copy the link_config.yaml file to the output folder
    config_output_path = os.path.join(output_folder, "link_config.yaml")
    shutil.copy2(config_path, config_output_path)
    
    # Create an instance of StreamDictCreator
    stream_dict_creator = StreamDictCreator(
        input_path=input_dir, output_path=output_folder, config_path=config_path,k_path_count=3
    )

    # Load data and create the stream dictionary
    packets, graph_nx = stream_dict_creator.load_data()
    stream_dict = stream_dict_creator.populate_stream_dict(packets, graph_nx)

    save_as_pkl(dict=stream_dict, folder_path=output_folder, name="stream_dict.pkl")

    print(f"Output saved in folder: {folder_name}")

if __name__ == "__main__":
    main()
