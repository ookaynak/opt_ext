from models.data_factory import DataFactory
from models.batches.optimization_model import OptimizationModel

class SimHandler:

    def __init__(self, data_factory: DataFactory):
        self.data_factory = data_factory
        self.optimization_model = OptimizationModel(data_factory)

    def set_initital_streams(self, streams):
        """
        Set the initial streams, that will be scheduled at the beginning of the simulation.
        :param streams: List of initial streams.
        """

    def set_lcm(self, lcm):
        """
        Set the lcm (Least Common Multiple), which is used to determine the scheduling period.
        Normally it is calculated from periods of all streams, if there are different periods will
        be added on the go additional to initial streams, we need to set the lcm manually, to avoid
        added streams changing the lcm. This is cycle in all switches
        :param lcm: The LCM to be set.
        """
    
    def add_stream(self, stream):
        """
        Add a new stream during the simulation, adds to the datafactory (not to the model).
        :param stream: The stream to be added.
        """

    def remove_stream(self, stream):
        """
        Remove a stream from datafactory (not from the model).
        :param stream: The stream to be removed.
        """

    def set_variable_streams(self, streams):
        """
        Set a not fixed stream variable in model for the next solve run..
        :param streams: List of variable streams.
        """
        
    def solve(self, max_batch_size=20):
        """
        Solve the optimization model.
        :return: The result of the optimization model.
        """
        return self.optimization_model.solve()
    

    def get_scheduled_streams(self):
        """
        Get the scheduled streams in previous solve.
        :return: List of scheduled streams.
        """
        return self.optimization_model.get_scheduled_streams()
    

    def fix_scheduled_streams(self):
        """
        Fix the scheduled streams.
        :param streams: List of streams to be fixed at model.
        """

    
    def unfix_fixed_streams(self):
        """
        Unfix the fixed stream at model.
        """

    def get_gate_control_list(self):
        """
        Get the gate control list, for a device. (also returns offset for talker)
        :return: List of gate controls.
        """
        return self.optimization_model.get_gate_control_list()
    
    def get_path_for_stream(self, stream):
        """
        Get the path for a stream.
        :param stream: The stream to get the path for.
        :return: The path for the stream.
        """
    

# EXAMPLE USAGE
data_factory = DataFactory(link_config=, graph_nx=, raw_streams=)
sim_handler = SimHandler(data_factory)

# Set initial streams
sim_handler.set_initital_streams(initial_streams)
sim_handler.set_lcm(lcm)
sim_handler.set_variable_streams(variable_streams)
sim_handler.solve(max_batch_size=20)
scheduled_streams = sim_handler.get_scheduled_streams()
sim_handler.fix_scheduled_streams(scheduled_streams)

# Initial run complete, returning to simulator
for port in Ports:
    sim_handler.get_gate_control_list
    SIMULATOR_GCL_FORMAT.append()
    return SIMULATOR_GCL_FORMAT

for stream in scheduled_streams:
    sim.handler.get_path_for_stream(stream)
    return SIMULATOR_PATH_FORMAT

# RUN SIMULATION

# ADD NEW STREAM REQUEST 
for stream in streams_to_add:
    sim_handler.add_stream(stream)

sim_handler.set_variable_streams(streams_to_add)
sim_handler.solve(max_batch_size=20)
scheduled_streams = sim_handler.get_scheduled_streams()
sim_handler.fix_scheduled_streams(scheduled_streams)

# Initial run complete, returning to simulator
for port in Ports:
    sim_handler.get_gate_control_list
    SIMULATOR_GCL_FORMAT.append()
    return SIMULATOR_GCL_FORMAT

for stream in scheduled_streams:
    sim.handler.get_path_for_stream(stream)
    return SIMULATOR_PATH_FORMAT

# CONTINUE SIMULATION

# REMOVE FIXED STREAM REQUEST
# stream not removed from data factory (can also be removed)
sim_handler.unfix_fixed_streams(stream)

for port in Ports:
    sim_handler.get_gate_control_list
    SIMULATOR_GCL_FORMAT.append()
    return SIMULATOR_GCL_FORMAT

# CONTINUE SIMULATION

# Notes:
# Assumptions :
# max_latency(stream) <= period(stream)
# LCM(periods) , for all periods, known or same for initial streams and consecutive additions
# packer creation time is always 0 for mod period(stream)