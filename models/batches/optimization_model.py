import pulp
import os
from models.data_factory import DataFactory


class OptimizationModel:
    """
    Core optimization model that handles the mathematical programming aspects
    of the stream scheduling problem.
    """

    def __init__(
        self, datafactory: DataFactory, output_path: str, time_limit: int = None
    ):
        """
        Initialize the optimization model.

        Args:
            datafactory: DataFactory instance with all stream data
            output_path: Directory to store solver outputs
            time_limit: Maximum solver time in seconds
        """
        self.datafactory = datafactory
        self.output_path = output_path
        self.time_limit = time_limit

        # Stream categorization
        self.variable_streams = []  # Streams being optimized in current iteration
        self.fixed_streams = []  # Streams with fixed schedules from prior iterations

        # Constraint tracking for dynamic updates
        self.variable_variable_constraints = []
        self.variable_fixed_constraints = []
        self.half_duplex_variable_variable_constraints = (
            []
        )  # Track HD var-var constraints
        self.half_duplex_variable_fixed_constraints = (
            []
        )  # Track HD var-fixed constraints

        # Decision variables
        self.dv_x = {}  # Start times
        self.dv_z = {}  # Path selection
        self.dv_a = {}  # Stream scheduling
        self.dv_yv = {}  # Variable-variable ordering (port level)
        self.dv_yf = {}  # Variable-fixed ordering (port level)
        self.dv_hdv = {}  # Half-duplex var-var ordering
        self.dv_hdf = {}  # Half-duplex var-fixed ordering

        # Counter for unique HDF variable names
        self._hdf_update_counter = 0

        # Initialize objective tracking
        self.objective_name = None

        # Create the problem and variables
        self.create_problem()
        self.create_base_variables()
        self.update_objective_function()  # Initialize with dummy objective
        self.setup_base_constraints()

    def create_problem(self):
        """Create the PuLP problem instance with the solver"""
        log_file_path = os.path.join(self.output_path, "solver_log.log")
        # Ensure output directory exists
        os.makedirs(self.output_path, exist_ok=True)
        self.solver = pulp.GUROBI(
            msg=True, logPath=log_file_path, timeLimit=self.time_limit
        )
        self.prob = pulp.LpProblem("Stream_Scheduling", pulp.LpMaximize)

    def create_base_variables(self):
        """Create all decision variables for the model"""
        # Start time variables
        self.dv_x = {
            (stream, path, repetition, port): pulp.LpVariable(
                f"x_{stream}_{path}_{repetition}_({port[0]},{port[1]})",
                lowBound=0,
                cat="Integer",  # Using Integer for potentially better performance with some solvers
            )
            for stream in self.datafactory.stream_dict.keys()
            for path in self.datafactory.stream_dict[stream].keys()
            for port in self.datafactory.stream_dict[stream][path]["ports"]
            for repetition in self.datafactory.stream_dict[stream][path]["repetitions"]
        }

        # Path selection variables (binary)
        self.dv_z = {
            (stream, path): pulp.LpVariable(
                f"z_{stream}_{path}",
                cat="Binary",
            )
            for stream in self.datafactory.stream_dict
            for path in self.datafactory.stream_dict[stream]
        }

        # Stream scheduling variables (binary)
        self.dv_a = {
            (stream): pulp.LpVariable(
                f"a_{stream}",
                cat="Binary",
            )
            for stream in self.datafactory.stream_dict
        }

    def update_objective_function(self, streams=None):
        """
        Define or update the objective function based on specified streams.

        Args:
            streams: List of stream indices to include in the objective.
                    If None, creates a dummy objective.
        """
        # Create new objective function
        if streams is None or len(streams) == 0:
            # Create a dummy objective (constant 1) if no streams are specified
            dummy_var = pulp.LpVariable(
                "dummy_objective", lowBound=0, upBound=1, cat="Integer"
            )
            self.prob.setObjective(dummy_var)
        else:
            # Create objective using specified streams
            self.prob.setObjective(
                pulp.lpSum(self.dv_a[(stream)] for stream in streams)
            )

    def setup_base_constraints(self):
        """Set up constraints that remain constant across all iterations"""
        self.add_constraint_1()  # Consecutive port timing
        self.add_constraint_4()  # Stream must reach final port
        self.add_constraint_5()  # Periodic repetitions
        # self.add_constraint_5_synced() # Alternative periodic constraint
        self.add_constraint_6()  # Time limit (LCM)
        self.add_constraint_7()  # Path selection
        self.add_constraint_8()  # Maximum latency
        self.add_constraint_9()  # Jitter constraint

    def add_constraint_1(self):
        """Add constraints for consecutive port timing within a path"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    for i, port in enumerate(
                        self.datafactory.stream_dict[stream][path]["ports"]
                    ):
                        if (
                            i
                            < len(self.datafactory.stream_dict[stream][path]["ports"])
                            - 1
                        ):
                            next_port = self.datafactory.get_next_port(
                                stream, path, port
                            )
                            # x_next = x_current + ns_current * z
                            self.prob += (
                                self.dv_x[(stream, path, repetition, port)]
                                + (
                                    (
                                        self.datafactory.stream_dict[stream][path][
                                            "ns"
                                        ][port]
                                    )
                                    * self.dv_z[(stream, path)]
                                )
                                == self.dv_x[(stream, path, repetition, next_port)]
                            )

    def add_constraint_4(self):
        """Stream must reach final port if scheduled (path selected)"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                first_repetition = self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ][0]
                last_port = self.datafactory.stream_dict[stream][path]["ports"][-1]
                # x_last >= z (ensures x_last is non-zero if z=1)
                self.prob += (
                    self.dv_x[(stream, path, first_repetition, last_port)]
                    >= self.dv_z[(stream, path)]
                )

    def add_constraint_5(self):
        """Enforce periodic repetitions start time lower bound"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                first_port = self.datafactory.stream_dict[stream][path]["ports"][0]
                period = self.datafactory.stream_dict[stream][path]["period"]
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    # x_rep >= (rep-1)*Period*z
                    self.prob += (
                        self.dv_x[(stream, path, repetition, first_port)]
                        >= (repetition - 1) * period * self.dv_z[(stream, path)]
                    )

    def add_constraint_5_synced(self):
        """Alternative: Enforce strict periodic repetitions based on the first repetition"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                first_port = self.datafactory.stream_dict[stream][path]["ports"][0]
                first_repetition = self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ][0]
                period = self.datafactory.stream_dict[stream][path]["period"]
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    self.prob += (
                        self.dv_x[(stream, path, first_repetition, first_port)]
                        + (repetition - 1) * period * self.dv_z[(stream, path)]
                        == self.dv_x[(stream, path, repetition, first_port)]
                    )

    #not necessary when max latency <= period and packet_ready_time = 0, with single lcm
    def add_constraint_6(self):
        """Time limit constraint (within LCM)"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                # Find the last repetition relevant within the LCM timeframe
                last_repetition_in_lcm = self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ][self.datafactory.stream_dict[stream][path]["last_rep_index"]]
                first_port = self.datafactory.stream_dict[stream][path]["ports"][0]
                # x_last_rep <= LCM
                self.prob += (
                    self.dv_x[(stream, path, last_repetition_in_lcm, first_port)]
                    <= self.datafactory.lcm + 1e-6  # Small tolerance
                )

    def add_constraint_7(self):
        """Path selection constraint: a stream is scheduled (a=1) iff exactly one path is selected (sum(z)=1)"""
        for stream in self.datafactory.stream_dict:
            self.prob += (
                pulp.lpSum(
                    self.dv_z[(stream, path)]
                    for path in self.datafactory.stream_dict[stream]
                )
                == self.dv_a[(stream)]
            )

    def add_constraint_8(self):
        """Maximum latency constraint"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    port = self.datafactory.stream_dict[stream][path]["ports"][-1]
                    self.prob += (
                        self.dv_x[(stream, path, repetition, port)]
                        + (
                            self.datafactory.get_time_for_stream_port(
                                stream, path, port
                            )
                            + self.datafactory.get_deviation_for_stream_port(
                                stream, path, port
                            )
                            * self.datafactory.stream_dict[stream][path]["gamma"][port]
                        )
                        * self.dv_z[(stream, path)]
                        <= self.datafactory.stream_dict[stream][path]["max_latency"] +
                        (self.datafactory.stream_dict[stream][path]["period"] * (repetition - 1))
                    )

    def add_constraint_9(self):
        """Jitter constraint"""
        for stream in self.datafactory.stream_dict:
            for path in self.datafactory.stream_dict[stream]:
                first_port = self.datafactory.stream_dict[stream][path]["ports"][0]
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    for repetition_2 in self.datafactory.stream_dict[stream][path][
                        "repetitions"
                    ]:
                        if repetition < repetition_2:
                            # Calculate the normalized offsets (arrival time minus expected periodic time)
                            offset_1 = self.dv_x[
                                (stream, path, repetition, first_port)
                            ] - (
                                (repetition - 1)
                                * self.datafactory.stream_dict[stream][path]["period"]
                            )
                            offset_2 = self.dv_x[
                                (stream, path, repetition_2, first_port)
                            ] - (
                                (repetition_2 - 1)
                                * self.datafactory.stream_dict[stream][path]["period"]
                            )

                            # First constraint: offset_1 - offset_2 >= -jitter (if path is selected)
                            # Equivalent to: offset_1 - offset_2 + M*(1-z) >= -jitter
                            # Where M is a large number
                            self.prob += (
                                offset_1
                                - offset_2
                                + self.datafactory.M * (1 - self.dv_z[(stream, path)])
                                >= -self.datafactory.stream_dict[stream][path][
                                    "max_jitter"
                                ]
                            )

                            # Second constraint: offset_1 - offset_2 <= jitter (if path is selected)
                            # Equivalent to: offset_1 - offset_2 - M*(1-z) <= jitter
                            self.prob += (
                                offset_1
                                - offset_2
                                - self.datafactory.M * (1 - self.dv_z[(stream, path)])
                                <= self.datafactory.stream_dict[stream][path][
                                    "max_jitter"
                                ]
                            )

    def is_wireless_node(self, node_name):
        """Helper function to check if a node is a wireless node based on its name"""
        # Checks if the node name contains the specific substrings indicating wireless capability
        return "-WN" in node_name

    def set_variable_streams(self, stream_indices):
        """Set which streams are variable in the current iteration"""
        # Reset variable streams list
        self.variable_streams = []

        # Add specified streams to variable list if they aren't already fixed
        for idx in stream_indices:
            if idx not in self.fixed_streams:
                self.variable_streams.append(idx)

        print(
            f"Set {len(self.variable_streams)} streams as variable: {self.variable_streams}"
        )
        print(f"Fixed streams: {self.fixed_streams}")

    def update_variable_variable_constraints(self):
        """Add ordering constraints between variable streams"""
        # Create a unique counter for this update
        update_id = id(self.variable_streams)

        # Clear existing port-level constraints and variables
        for constraint_name in self.variable_variable_constraints:
            del self.prob.constraints[constraint_name]
        self.variable_variable_constraints = []
        self.dv_yv = {}  # Reset binary variables

        # Update the objective function to focus on variable streams
        self.update_objective_function(self.variable_streams)

        # Create yv variables for ordering decisions with unique names
        self.dv_yv.update(
            {
                (
                    stream,
                    path,
                    stream_2,
                    path_2,
                    repetition,
                    repetition_2,
                    port,
                ): pulp.LpVariable(
                    # Using a simpler naming scheme for potentially shorter names
                    f"yv_{update_id}_{stream}_{path}_{stream_2}_{path_2}_{repetition}_{repetition_2}_{port[0]}_{port[1]}",
                    cat="Binary",
                )
                for stream in self.variable_streams
                for path in self.datafactory.stream_dict[stream].keys()
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]
                for port in self.datafactory.stream_dict[stream][path]["ports"]
                # Iterate through potentially conflicting streams on the same port
                for stream_2 in self.datafactory.get_streams_for_port(port)
                # Ensure both streams are variable and avoid duplicate pairs (stream < stream_2)
                if stream < stream_2 and stream_2 in self.variable_streams
                for path_2 in self.datafactory.get_paths_for_port_stream(stream_2, port)
                for repetition_2 in self.datafactory.stream_dict[stream_2][path_2][
                    "repetitions"
                ]
            }
        )

        # Add ordering constraints for variable streams sharing a port
        constraint_count = 0
        for stream in self.variable_streams:
            for path in self.datafactory.stream_dict[stream].keys():
                for repetition in self.datafactory.stream_dict[stream][path][
                    "repetitions"
                ]:
                    for port in self.datafactory.stream_dict[stream][path]["ports"]:
                        for stream_2 in self.datafactory.get_streams_for_port(port):
                            # Only process pairs where both are variable and stream < stream_2
                            if stream < stream_2 and stream_2 in self.variable_streams:
                                for (
                                    path_2
                                ) in self.datafactory.get_paths_for_port_stream(
                                    stream_2, port
                                ):
                                    for repetition_2 in self.datafactory.stream_dict[
                                        stream_2
                                    ][path_2]["repetitions"]:
                                        # Key for the binary variable
                                        yv_key = (
                                            stream,
                                            path,
                                            stream_2,
                                            path_2,
                                            repetition,
                                            repetition_2,
                                            port,
                                        )

                                        # Calculate processing times and buffer periods
                                        proc_time_1 = (
                                            self.datafactory.get_time_for_stream_port(
                                                stream, path, port
                                            )
                                        )
                                        dev_1 = self.datafactory.get_deviation_for_stream_port(
                                            stream, path, port
                                        )
                                        gamma_1 = self.datafactory.stream_dict[stream][
                                            path
                                        ]["gamma"].get(port, 1.0)
                                        bp_1 = self.datafactory.stream_dict[stream][
                                            path
                                        ]["bp"].get(
                                            self.datafactory.get_previous_port(
                                                stream, path, port
                                            ),
                                            0,
                                        )

                                        proc_time_2 = (
                                            self.datafactory.get_time_for_stream_port(
                                                stream_2, path_2, port
                                            )
                                        )
                                        dev_2 = self.datafactory.get_deviation_for_stream_port(
                                            stream_2, path_2, port
                                        )
                                        gamma_2 = self.datafactory.stream_dict[
                                            stream_2
                                        ][path_2]["gamma"].get(port, 1.0)
                                        bp_2 = self.datafactory.stream_dict[stream_2][
                                            path_2
                                        ]["bp"].get(
                                            self.datafactory.get_previous_port(
                                                stream_2, path_2, port
                                            ),
                                            0,
                                        )

                                        # Constraint 1: stream finishes before stream_2 starts (if yv=1)
                                        # x1 + (proc1 + dev1*gamma1)*z1 <= x2 - bp2*z2 + M*yv
                                        constraint_name = (
                                            f"var_var_1_{constraint_count}"
                                        )
                                        self.prob.constraints[constraint_name] = (
                                            self.dv_x[(stream, path, repetition, port)]
                                            + (proc_time_1 + dev_1 * gamma_1)
                                            * self.dv_z[(stream, path)]
                                            <= self.dv_x[
                                                (
                                                    stream_2,
                                                    path_2,
                                                    repetition_2,
                                                    port,
                                                )
                                            ]
                                            - bp_2 * self.dv_z[(stream_2, path_2)]
                                            + self.datafactory.M * self.dv_yv[yv_key]
                                        )
                                        self.variable_variable_constraints.append(
                                            constraint_name
                                        )

                                        # Constraint 2: stream_2 finishes before stream starts (if yv=0)
                                        # x2 + (proc2 + dev2*gamma2)*z2 <= x1 - bp1*z1 + M*(1-yv)
                                        constraint_name = (
                                            f"var_var_2_{constraint_count}"
                                        )
                                        self.prob.constraints[
                                            constraint_name
                                        ] = self.dv_x[
                                            (
                                                stream_2,
                                                path_2,
                                                repetition_2,
                                                port,
                                            )
                                        ] + (
                                            proc_time_2 + dev_2 * gamma_2
                                        ) * self.dv_z[
                                            (stream_2, path_2)
                                        ] <= self.dv_x[
                                            (stream, path, repetition, port)
                                        ] - bp_1 * self.dv_z[
                                            (stream, path)
                                        ] + self.datafactory.M * (
                                            1 - self.dv_yv[yv_key]
                                        )
                                        self.variable_variable_constraints.append(
                                            constraint_name
                                        )
                                        constraint_count += 1

        if constraint_count > 0:
            print(f"Added {constraint_count} variable-variable port constraints")

        # Add half-duplex constraints for variable-variable streams
        self.update_half_duplex_variable_variable_constraints()  # Call the new method

    def update_half_duplex_variable_variable_constraints(self):
        """
        Add half-duplex constraints to ensure uplink and downlink slots for the same wireless device
        don't overlap when both streams are variable.
        """
        # Create a unique counter for this update
        update_id = id(self.variable_streams) + 1000  # Offset to distinguish

        # Clear existing constraints and variables
        for constraint_name in self.half_duplex_variable_variable_constraints:
            del self.prob.constraints[constraint_name]
        self.half_duplex_variable_variable_constraints = []
        self.dv_hdv = {}  # Reset binary variables

        # Dictionary to map wireless devices to their ports
        wireless_device_port_map = {}

        # Identify all wireless devices and their associated ports for variable streams
        for stream in self.variable_streams:
            for path in self.datafactory.stream_dict[stream]:
                for port in self.datafactory.stream_dict[stream][path]["ports"]:
                    source, dest = port

                    # Check source (downlink from wireless device)
                    if self.is_wireless_node(source):
                        device = source
                        if device not in wireless_device_port_map:
                            wireless_device_port_map[device] = {
                                "uplink": [],
                                "downlink": [],
                            }
                        wireless_device_port_map[device]["downlink"].append(
                            (stream, path, port)
                        )

                    # Check destination (uplink to wireless device)
                    if self.is_wireless_node(dest):
                        device = dest
                        if device not in wireless_device_port_map:
                            wireless_device_port_map[device] = {
                                "uplink": [],
                                "downlink": [],
                            }
                        wireless_device_port_map[device]["uplink"].append(
                            (stream, path, port)
                        )

        # Create binary variables and constraints
        constraint_count = 0
        for device, port_info in wireless_device_port_map.items():
            uplink_ports = port_info["uplink"]
            downlink_ports = port_info["downlink"]

            # Compare each uplink stream with each downlink stream using the same device
            for up_stream, up_path, up_port in uplink_ports:
                for down_stream, down_path, down_port in downlink_ports:
                    # Ensure both streams are variable and avoid self-comparison
                    # (A stream might use the same WN for uplink then downlink later in its path)
                    if up_stream == down_stream:
                        continue  # Skip if the same stream instance

                    # Iterate through repetitions
                    for up_repetition in self.datafactory.stream_dict[up_stream][
                        up_path
                    ]["repetitions"]:
                        for down_repetition in self.datafactory.stream_dict[
                            down_stream
                        ][down_path]["repetitions"]:
                            # Create binary variable for ordering
                            hd_key = (
                                up_stream,
                                up_path,
                                up_repetition,
                                up_port,
                                down_stream,
                                down_path,
                                down_repetition,
                                down_port,
                            )

                            self.dv_hdv[hd_key] = pulp.LpVariable(
                                f"hdv_{update_id}_{up_stream}_{up_path}_{up_repetition}_{up_port[0]}_{up_port[1]}_"
                                f"{down_stream}_{down_path}_{down_repetition}_{down_port[0]}_{down_port[1]}",
                                cat="Binary",
                            )

                            # Calculate relevant times and buffer periods
                            up_proc_time = self.datafactory.get_time_for_stream_port(
                                up_stream, up_path, up_port
                            )
                            up_deviation = (
                                self.datafactory.get_deviation_for_stream_port(
                                    up_stream, up_path, up_port
                                )
                            )
                            up_gamma = self.datafactory.stream_dict[up_stream][up_path][
                                "gamma"
                            ].get(up_port, 1.0)
                            up_bp = self.datafactory.stream_dict[up_stream][up_path][
                                "bp"
                            ].get(
                                self.datafactory.get_previous_port(
                                    up_stream, up_path, up_port
                                ),
                                0,
                            )

                            down_proc_time = self.datafactory.get_time_for_stream_port(
                                down_stream, down_path, down_port
                            )
                            down_deviation = (
                                self.datafactory.get_deviation_for_stream_port(
                                    down_stream, down_path, down_port
                                )
                            )
                            down_gamma = self.datafactory.stream_dict[down_stream][
                                down_path
                            ]["gamma"].get(down_port, 1.0)
                            down_bp = self.datafactory.stream_dict[down_stream][
                                down_path
                            ]["bp"].get(
                                self.datafactory.get_previous_port(
                                    down_stream, down_path, down_port
                                ),
                                0,
                            )

                            # Constraint 1: Uplink finishes before Downlink starts (if hdv=1)
                            # x_up + (proc_up + dev_up*gamma_up)*z_up <= x_down - bp_down*z_down + M*hdv
                            constraint_name = f"hd_var_var_1_{constraint_count}"
                            self.prob.constraints[constraint_name] = (
                                self.dv_x[(up_stream, up_path, up_repetition, up_port)]
                                + (up_proc_time + up_deviation * up_gamma)
                                * self.dv_z[(up_stream, up_path)]
                                <= self.dv_x[
                                    (
                                        down_stream,
                                        down_path,
                                        down_repetition,
                                        down_port,
                                    )
                                ]
                                - down_bp * self.dv_z[(down_stream, down_path)]
                                + self.datafactory.M * self.dv_hdv[hd_key]
                            )
                            self.half_duplex_variable_variable_constraints.append(
                                constraint_name
                            )

                            # Constraint 2: Downlink finishes before Uplink starts (if hdv=0)
                            # x_down + (proc_down + dev_down*gamma_down)*z_down <= x_up - bp_up*z_up + M*(1-hdv)
                            constraint_name = f"hd_var_var_2_{constraint_count}"
                            self.prob.constraints[constraint_name] = self.dv_x[
                                (
                                    down_stream,
                                    down_path,
                                    down_repetition,
                                    down_port,
                                )
                            ] + (
                                down_proc_time + down_deviation * down_gamma
                            ) * self.dv_z[
                                (down_stream, down_path)
                            ] <= self.dv_x[
                                (up_stream, up_path, up_repetition, up_port)
                            ] - up_bp * self.dv_z[
                                (up_stream, up_path)
                            ] + self.datafactory.M * (
                                1 - self.dv_hdv[hd_key]
                            )
                            self.half_duplex_variable_variable_constraints.append(
                                constraint_name
                            )

                            constraint_count += 1

        if constraint_count > 0:
            print(f"Added {constraint_count} half-duplex variable-variable constraints")

    def update_variable_fixed_constraints(self):
        """
        Add ordering constraints between variable streams and fixed blocked ranges at the port level.
        """
        # Create a unique counter for this update
        update_id = id(self.variable_streams) + id(self.fixed_streams)

        # Clear existing port-level constraints and variables
        for constraint_name in self.variable_fixed_constraints:
            del self.prob.constraints[constraint_name]
        self.variable_fixed_constraints = []
        self.dv_yf = {}  # Reset binary variables

        # Create binary variables and constraints for each port
        constraint_count = 0

        # For each variable stream and path that uses this port
        for var_stream in self.variable_streams:
            for var_path in self.datafactory.stream_dict[var_stream]:
                for port in self.datafactory.stream_dict[var_stream][var_path]["ports"]:
                    # Calculate variable length for this stream-path-port combination
                    variable_bp = self.datafactory.stream_dict[var_stream][var_path][
                        "bp"
                    ].get(
                        self.datafactory.get_previous_port(var_stream, var_path, port),
                        0,
                    )
                    variable_proc_time = self.datafactory.get_time_for_stream_port(
                        var_stream, var_path, port
                    )
                    variable_deviation = self.datafactory.get_deviation_for_stream_port(
                        var_stream, var_path, port
                    )
                    variable_gamma = self.datafactory.stream_dict[var_stream][var_path][
                        "gamma"
                    ].get(port, 1.0)
                    variable_length = (
                        variable_bp
                        + variable_proc_time
                        + variable_deviation * variable_gamma
                    )

                    # Get blocked ranges based on the calculated length needed by the variable stream
                    blocked_ranges = self.calculate_blocked_ranges(
                        port, variable_length
                    )

                    # Skip if no blocked ranges at this port
                    if not blocked_ranges:
                        continue

                    # Create binary variables and constraints for each repetition and blocked range
                    for repetition in self.datafactory.stream_dict[var_stream][
                        var_path
                    ]["repetitions"]:
                        for block_idx, (block_start, block_duration) in enumerate(
                            blocked_ranges
                        ):
                            # Create a binary variable with the unique counter in the name
                            block_var_key = (
                                var_stream,
                                var_path,
                                repetition,
                                port,
                                block_idx,
                            )
                            self.dv_yf[block_var_key] = pulp.LpVariable(
                                f"yf_{update_id}_{var_stream}_{var_path}_{repetition}_{port[0]}_{port[1]}_{block_idx}",
                                cat="Binary",
                            )

                            # Calculate block end time
                            block_end = block_start + block_duration

                            # Constraint 1: Variable stream finishes before block starts (if yf=0)
                            # x_var + (proc_var + dev_var*gamma_var)*z_var <= block_start + M * yf
                            constraint_name = f"var_fixed_before_{constraint_count}"
                            self.prob.constraints[constraint_name] = (
                                self.dv_x[(var_stream, var_path, repetition, port)]
                                + (
                                    variable_proc_time
                                    + variable_deviation * variable_gamma
                                )
                                * self.dv_z[(var_stream, var_path)]
                                <= block_start
                                + self.datafactory.M * self.dv_yf[block_var_key]
                            )
                            self.variable_fixed_constraints.append(constraint_name)

                            # Constraint 2: Variable stream starts after block ends (if yf=1)
                            # x_var - bp_var*z_var >= block_end - M * (1 - yf)
                            constraint_name = f"var_fixed_after_{constraint_count}"
                            self.prob.constraints[constraint_name] = self.dv_x[
                                (var_stream, var_path, repetition, port)
                            ] - variable_bp * self.dv_z[
                                (var_stream, var_path)
                            ] >= block_end - self.datafactory.M * (
                                1 - self.dv_yf[block_var_key]
                            )
                            self.variable_fixed_constraints.append(constraint_name)

                            constraint_count += 1

        if constraint_count > 0:
            print(f"Added {constraint_count} variable-fixed port constraints")

        # Add half-duplex constraints for variable-fixed streams
        self.update_half_duplex_variable_fixed_constraints()  # Call the new method

    def update_half_duplex_variable_fixed_constraints(self):
        """
        Add half-duplex constraints to ensure uplink and downlink slots for the same wireless device
        don't overlap when one stream is variable and the other is fixed, using blocked ranges.
        Iterates through variable streams and applies constraints against fixed stream schedules.
        """
        # Increment update counter for unique variable names in this call
        self._hdf_update_counter += 1
        current_update_id = self._hdf_update_counter

        # Clear existing constraints and variables from the previous update
        for constraint_name in self.half_duplex_variable_fixed_constraints:
            # Use try-except for robustness if constraint was already removed elsewhere
            try:
                if constraint_name in self.prob.constraints:
                    del self.prob.constraints[constraint_name]
            except KeyError:
                print(
                    f"Warning: Constraint {constraint_name} not found during HDF cleanup."
                )
        self.half_duplex_variable_fixed_constraints = []
        self.dv_hdf = {}  # Reset binary variables for this constraint type

        # Skip if no variable or no fixed streams
        if not self.variable_streams or not self.fixed_streams:
            return

        # --- Pre-calculate Fixed Schedule Information ---
        # Store fixed schedule details indexed by device and direction
        fixed_schedule_by_device = {}  # {device: {"uplink": [...], "downlink": [...]}}
        for fixed_stream in self.fixed_streams:
            scheduled_path = self.get_scheduled_path(fixed_stream)
            if scheduled_path is None:
                continue

            for port in self.datafactory.stream_dict[fixed_stream][scheduled_path][
                "ports"
            ]:
                source, dest = port
                device = None
                direction = None

                if self.is_wireless_node(source):
                    device = source
                    direction = "downlink"  # Fixed stream is downlink FROM device
                elif self.is_wireless_node(dest):
                    device = dest
                    direction = "uplink"  # Fixed stream is uplink TO device

                if device and direction:
                    # Initialize device entry if needed
                    if device not in fixed_schedule_by_device:
                        fixed_schedule_by_device[device] = {
                            "uplink": [],
                            "downlink": [],
                        }

                    # Store schedule details for each repetition
                    for rep in self.datafactory.stream_dict[fixed_stream][
                        scheduled_path
                    ]["repetitions"]:
                        key = (fixed_stream, scheduled_path, rep, port)
                        x_var = self.dv_x.get(key)
                        if x_var is not None and x_var.value() is not None:
                            fixed_schedule_by_device[device][direction].append(
                                (x_var.value(), fixed_stream, scheduled_path, rep, port)
                            )
                        # else: # Should not happen for fixed streams, but log if it does
                        #    print(f"Warning: Missing value for fixed stream {key} in HDF calculation.")

        # --- Iterate Through Variable Streams and Apply Constraints ---
        constraint_count = 0
        for var_stream in self.variable_streams:
            for var_path in self.datafactory.stream_dict[var_stream]:
                for var_port in self.datafactory.stream_dict[var_stream][var_path][
                    "ports"
                ]:
                    var_source, var_dest = var_port
                    var_device = None
                    var_direction = (
                        None  # Direction of the variable stream at this port
                    )

                    if self.is_wireless_node(var_source):
                        var_device = var_source
                        var_direction = (
                            "downlink"  # Variable stream is downlink FROM device
                        )
                    elif self.is_wireless_node(var_dest):
                        var_device = var_dest
                        var_direction = "uplink"  # Variable stream is uplink TO device

                    # If this port involves a wireless device used by fixed streams
                    if var_device and var_device in fixed_schedule_by_device:

                        # Determine the direction of fixed streams to constrain against
                        fixed_direction_to_block = (
                            "uplink" if var_direction == "downlink" else "downlink"
                        )
                        fixed_schedule_tuples = fixed_schedule_by_device[
                            var_device
                        ].get(fixed_direction_to_block, [])

                        # Only proceed if there are fixed streams in the opposite direction
                        if fixed_schedule_tuples:
                            # Calculate the effective length needed by the variable stream at this port
                            var_bp = self.datafactory.stream_dict[var_stream][var_path][
                                "bp"
                            ].get(
                                self.datafactory.get_previous_port(
                                    var_stream, var_path, var_port
                                ),
                                0,
                            )
                            var_proc = self.datafactory.get_time_for_stream_port(
                                var_stream, var_path, var_port
                            )
                            var_dev = self.datafactory.get_deviation_for_stream_port(
                                var_stream, var_path, var_port
                            )
                            var_gamma = self.datafactory.stream_dict[var_stream][
                                var_path
                            ]["gamma"].get(var_port, 1.0)
                            variable_length = var_bp + var_proc + var_dev * var_gamma

                            # Calculate blocked ranges caused by the fixed streams in the opposite direction
                            blocked_ranges = self.calculate_blocked_ranges_hd(
                                fixed_schedule_tuples, variable_length
                            )

                            if not blocked_ranges:
                                continue  # No blocking ranges from fixed streams

                            # Add constraints for each variable repetition against each blocked range
                            for var_repetition in self.datafactory.stream_dict[
                                var_stream
                            ][var_path]["repetitions"]:
                                for block_idx, (
                                    block_start,
                                    block_duration,
                                ) in enumerate(blocked_ranges):
                                    block_end = block_start + block_duration

                                    # Create unique binary variable key and variable
                                    # Include var_stream, path, rep, port, device, fixed_direction, block_idx, and update_id
                                    block_var_key = (
                                        var_stream,
                                        var_path,
                                        var_repetition,
                                        var_port,
                                        var_device,
                                        fixed_direction_to_block,
                                        block_idx,
                                    )
                                    hdf_var_name = (
                                        f"hdf_{current_update_id}_{var_stream}_{var_path}_{var_repetition}_"
                                        f"{var_port[0]}_{var_port[1]}_{var_device}_{block_idx}"
                                    )
                                    self.dv_hdf[block_var_key] = pulp.LpVariable(
                                        hdf_var_name, cat="Binary"
                                    )

                                    # Constraint 1: Variable stream ends before Fixed block starts (if hdf=0)
                                    # x_var + (proc_var + dev_var*gamma_var)*z_var <= block_start + M * hdf
                                    constraint_name = (
                                        f"hd_var_fixed_before_{constraint_count}"
                                    )
                                    self.prob.constraints[constraint_name] = (
                                        self.dv_x[
                                            (
                                                var_stream,
                                                var_path,
                                                var_repetition,
                                                var_port,
                                            )
                                        ]
                                        + (var_proc + var_dev * var_gamma)
                                        * self.dv_z[(var_stream, var_path)]
                                        <= block_start
                                        + self.datafactory.M
                                        * self.dv_hdf[block_var_key]
                                    )
                                    self.half_duplex_variable_fixed_constraints.append(
                                        constraint_name
                                    )

                                    # Constraint 2: Variable stream starts after Fixed block ends (if hdf=1)
                                    # x_var - bp_var*z_var >= block_end - M * (1 - hdf)
                                    constraint_name = (
                                        f"hd_var_fixed_after_{constraint_count}"
                                    )
                                    self.prob.constraints[constraint_name] = self.dv_x[
                                        (var_stream, var_path, var_repetition, var_port)
                                    ] - var_bp * self.dv_z[
                                        (var_stream, var_path)
                                    ] >= block_end - self.datafactory.M * (
                                        1 - self.dv_hdf[block_var_key]
                                    )
                                    self.half_duplex_variable_fixed_constraints.append(
                                        constraint_name
                                    )
                                    constraint_count += 1

        if constraint_count > 0:
            print(
                f"Added {constraint_count} half-duplex variable-fixed constraints (Update ID: {current_update_id})"
            )
        # else:
        #    print(f"No half-duplex variable-fixed constraints needed (Update ID: {current_update_id})")

    def get_scheduled_path(self, stream):
        """Get the path selected for a scheduled stream"""
        # Check if stream 'a' variable exists and is scheduled
        a_var = self.dv_a.get(stream)
        if a_var is None or a_var.value() is None or a_var.value() < 0.5:
            return None  # Stream not scheduled or value not available

        # Find the path 'z' variable that is set to 1
        for path in self.datafactory.stream_dict[stream]:
            z_var = self.dv_z.get((stream, path))
            if z_var is not None and z_var.value() is not None and z_var.value() > 0.5:
                return path
        # This should ideally not happen if a=1, but return None as fallback
        # print(f"Warning: Stream {stream} has a=1 but no path z=1 found.")
        return None

    def get_newly_scheduled_streams(self):
        """Check which variable streams were scheduled in the current iteration"""
        newly_scheduled = []

        for stream in list(self.variable_streams):  # Iterate over a copy
            a_var = self.dv_a.get(stream)
            if a_var is not None and a_var.value() is not None and a_var.value() > 0.5:
                newly_scheduled.append(stream)

        print(f"Newly scheduled streams: {newly_scheduled}")
        print(f"Previously scheduled streams: {len(self.fixed_streams)}")

        return newly_scheduled

    def fix_stream(self, stream):
        """
        Fix variables for a single stream that was successfully scheduled.

        Args:
            stream: Stream index to fix

        Returns:
            bool: True if fixing was successful, False otherwise
        """
        # Check if stream is not fixed already
        if stream in self.fixed_streams:
            print(f"Warning: Stream {stream} is already fixed, nothing to do")
            return False

        # Check if stream is in variable streams
        if stream not in self.variable_streams:
            print(f"Warning: Stream {stream} is not in variable_streams, can't fix it")
            return False

        # Initialize constraint tracking dictionary if it doesn't exist
        if not hasattr(self, "fixed_constraints"):
            self.fixed_constraints = {}

        # Initialize list of constraints for this stream
        self.fixed_constraints[stream] = []

        # Get the scheduled path
        scheduled_path = self.get_scheduled_path(stream)
        if scheduled_path is None:
            a_val = self.dv_a.get(stream).value() if self.dv_a.get(stream) else "N/A"
            print(
                f"Error: Stream {stream} marked for fixing but no scheduled path found (a={a_val}). Cannot fix."
            )
            # Optionally, unschedule the stream if path is missing despite a=1
            # self.dv_a[(stream)].setInitialValue(0) # Requires solver re-run potentially
            return False

        # Store current values of x variables for the scheduled path
        current_values_x = {}
        for repetition in self.datafactory.stream_dict[stream][scheduled_path][
            "repetitions"
        ]:
            for port in self.datafactory.stream_dict[stream][scheduled_path]["ports"]:
                key = (stream, scheduled_path, repetition, port)
                x_var = self.dv_x.get(key)
                if x_var is not None and x_var.value() is not None:
                    current_values_x[key] = x_var.value()
                else:
                    print(
                        f"Error: Missing value for x variable {key} for stream {stream} to be fixed."
                    )
                    return False  # Cannot fix if values are missing

        # Fix a variable to 1
        constraint_name = f"fix_a_{stream}"
        self.prob += self.dv_a[(stream)] == 1, constraint_name
        self.fixed_constraints[stream].append(constraint_name)

        # Fix z variables - 1 for scheduled path, 0 for others
        for path in self.datafactory.stream_dict[stream]:
            value = 1 if path == scheduled_path else 0
            constraint_name = f"fix_z_{stream}_{path}"
            self.prob += self.dv_z[(stream, path)] == value, constraint_name
            self.fixed_constraints[stream].append(constraint_name)

        # Fix x variables for the scheduled path using stored values
        for key, value in current_values_x.items():
            # Construct constraint name carefully
            s, p, r, pt = key
            constraint_name = f"fix_x_{s}_{p}_{r}_{pt[0]}_{pt[1]}"
            self.prob += (
                self.dv_x[key] == value,
                constraint_name,
            )
            self.fixed_constraints[stream].append(constraint_name)

        # Update stream status
        self.fixed_streams.append(stream)
        self.variable_streams.remove(stream)

        print(
            f"Fixed stream {stream} with path {scheduled_path} using {len(self.fixed_constraints[stream])} constraints"
        )
        return True

    def fix_scheduled_stream_variables(self, streams_to_fix):
        """
        Fix variables for multiple streams that were successfully scheduled.

        Args:
            streams_to_fix: List of stream indices to fix
        """
        fixed_count = 0
        failed_count = 0
        for stream in streams_to_fix:
            if self.fix_stream(stream):
                fixed_count += 1
            else:
                failed_count += 1
        print(
            f"Attempted to fix {len(streams_to_fix)} streams. Success: {fixed_count}, Failed: {failed_count}"
        )

    def unfix_stream(self, stream):
        """
        Remove all fixation constraints for a specific stream, making it variable again.

        Args:
            stream: Stream index to unfix

        Returns:
            bool: True if unfixing was successful, False otherwise
        """
        # Check if stream is fixed
        if stream not in self.fixed_streams:
            print(f"Warning: Stream {stream} is not in fixed_streams, nothing to unfix")
            return False

        # Check if we have constraint records for this stream
        if (
            not hasattr(self, "fixed_constraints")
            or stream not in self.fixed_constraints
        ):
            print(f"Warning: No fixation constraints found for stream {stream}")
            # Proceed to update status anyway, assuming constraints might have been lost
            self.fixed_streams.remove(stream)
            if stream not in self.variable_streams:
                self.variable_streams.append(stream)
            return True  # Indicate status updated, though constraints weren't removed

        # Remove all tracked constraints for this stream
        constraint_count = len(self.fixed_constraints[stream])
        removed_count = 0
        for constraint_name in self.fixed_constraints[stream]:
            if constraint_name in self.prob.constraints:
                del self.prob.constraints[constraint_name]
                removed_count += 1
            else:
                print(
                    f"Warning: Constraint {constraint_name} for stream {stream} not found in model."
                )

        # Clear constraint tracking for this stream
        del self.fixed_constraints[stream]

        # Update stream status
        self.fixed_streams.remove(stream)
        if stream not in self.variable_streams:  # Avoid duplicates
            self.variable_streams.append(stream)

        print(
            f"Unfixed stream {stream}, removed {removed_count}/{constraint_count} constraints"
        )
        return True

    def get_solution_variables(self):
        """Get all solution variables with clean values"""
        # All variables raw values
        variables_raw = {var.name: var.value() for var in self.prob.variables()}

        # Extract x variables (start times) - only non-None
        variables_x = {
            key: var.value()
            for key, var in self.dv_x.items()
            if var.value() is not None
        }

        # Extract y variables (ordering) - only non-None
        variables_y = {}
        for key, var in self.dv_yv.items():
            if var.value() is not None:
                variables_y[key] = var.value()
        for key, var in self.dv_yf.items():
            if var.value() is not None:
                variables_y[key] = var.value()
        for key, var in self.dv_hdv.items():
            if var.value() is not None:
                variables_y[key] = var.value()
        for key, var in self.dv_hdf.items():
            if var.value() is not None:
                variables_y[key] = var.value()

        # Extract z variables (path selection) - cleaned to 0 or 1
        variables_z = {}
        for stream in self.datafactory.stream_dict:
            scheduled_path = self.get_scheduled_path(
                stream
            )  # Uses current solution values
            for path in self.datafactory.stream_dict[stream]:
                key = (stream, path)
                variables_z[key] = 1 if path == scheduled_path else 0

        # Extract a variables (stream scheduling) - cleaned to 0 or 1
        variables_a = {}
        for stream in self.datafactory.stream_dict:
            a_var = self.dv_a.get(stream)
            val = a_var.value() if a_var else None
            variables_a[stream] = 1 if val is not None and val > 0.5 else 0

        return variables_raw, variables_x, variables_y, variables_z, variables_a

    def solve(self, iteration=None):
        """
        Solve the current model

        Args:
            iteration: The current iteration number (used for log files)

        Returns:
            String: Solution status
        """
        # Create iteration-specific log file if an iteration is provided
        if iteration is not None:
            log_file_path = os.path.join(
                self.output_path, f"solver_log_iteration_{iteration}.log"
            )
            lp_file_path = os.path.join(
                self.output_path, f"model_iteration_{iteration}.lp"
            )
            # Uncomment to write LP file for debugging specific iterations
            # try:
            #     self.prob.writeLP(lp_file_path)
            #     print(f"Exported LP model for iteration {iteration} to {lp_file_path}")
            # except Exception as e:
            #     print(f"Error writing LP file for iteration {iteration}: {e}")
        else:
            log_file_path = os.path.join(self.output_path, "solver_log.log")
            lp_file_path = os.path.join(self.output_path, "model.lp")
            # Uncomment to write the final LP file
            # try:
            #     self.prob.writeLP(lp_file_path)
            #     print(f"Exported LP model to {lp_file_path}")
            # except Exception as e:
            #     print(f"Error writing LP file: {e}")

        # Update the solver with the potentially new log file path
        self.solver = pulp.GUROBI(
            msg=True, logPath=log_file_path, timeLimit=self.time_limit
        )

        # Solve the problem
        status = self.prob.solve(self.solver)
        return pulp.LpStatus[status]

    def get_fixed_stream_port_schedule(self, port):
        """
        Get the start times for all fixed streams at a specific port, using current variable values.

        Args:
            port: The port identifier tuple (e.g., ('0-SW1', '0-SW2'))

        Returns:
            List of tuples: [(start_time, stream, path, repetition, port_used), ...] sorted by start_time
        """
        scheduled_times = []

        # Only check fixed streams
        for stream in self.fixed_streams:
            # Get the path that was selected for this stream
            scheduled_path = self.get_scheduled_path(stream)
            if scheduled_path is None:
                continue  # Should not happen for fixed streams, but check anyway

            # Check if this path uses the specified port
            if (
                port
                not in self.datafactory.stream_dict[stream][scheduled_path]["ports"]
            ):
                continue

            # Get all repetitions and their start times at this port
            for repetition in self.datafactory.stream_dict[stream][scheduled_path][
                "repetitions"
            ]:
                key = (stream, scheduled_path, repetition, port)
                x_var = self.dv_x.get(key)
                start_time = x_var.value() if x_var is not None else None

                if start_time is not None:
                    scheduled_times.append(
                        (
                            start_time,
                            stream,
                            scheduled_path,
                            repetition,
                            port,
                        )  # Include port used
                    )

        # Sort by start time
        scheduled_times.sort()

        return scheduled_times

    def print_fixed_port_schedule(self, port):
        """
        Print the schedule of fixed streams at a specific port in a nice format.

        Args:
            port: The port identifier (e.g., ('0-SW1', '0-SW2'))
        """
        schedule = self.get_fixed_stream_port_schedule(port)

        if not schedule:
            print(f"\nNo fixed streams scheduled at port {port}")
            return

        print(f"\n=== Fixed Stream Schedule for Port {port} ===")
        print(
            f"{'Stream':<7} {'Path':<6} {'Repetition':<10} {'Start':<10} {'Duration':<10} {'End':<10}"
        )
        print("-" * 60)

        schedule_details = []  # Store details for timeline
        for start_time, stream, path, repetition, port_used in schedule:
            # Calculate buffering period for this stream at this port
            bp = self.datafactory.stream_dict[stream][path]["bp"].get(
                self.datafactory.get_previous_port(stream, path, port_used), 0
            )

            # Calculate processing time (including deviation)
            proc_time = self.datafactory.get_time_for_stream_port(
                stream, path, port_used
            )
            dev = self.datafactory.get_deviation_for_stream_port(
                stream, path, port_used
            )
            gamma = self.datafactory.stream_dict[stream][path]["gamma"].get(
                port_used, 1.0
            )
            total_proc_time = proc_time + dev * gamma

            # Calculate effective start and end times including buffer
            effective_start = start_time - bp
            effective_end = start_time + total_proc_time
            effective_duration = effective_end - effective_start

            schedule_details.append(
                (effective_start, effective_end, stream, repetition)
            )

            # Print the details
            print(
                f"{stream:<7} {path:<6} {repetition:<10} {effective_start:<10.2f} {effective_duration:<10.2f} {effective_end:<10.2f}"
            )

        # Add a simple timeline visualization
        print("\nTimeline (Effective Start/End including Buffering):")
        if schedule_details:
            # Find max effective end time
            max_time = 0
            for eff_start, eff_end, _, _ in schedule_details:
                max_time = max(max_time, eff_end)

            timeline_width = 60
            scale = (
                timeline_width / max_time if max_time > 1e-9 else 1
            )  # Avoid division by zero

            print("0" + " " * (timeline_width - 1) + f"{max_time:.1f}")
            print("|" + "-" * (timeline_width) + "|")  # Adjusted width

            # Sort by effective start time for printing timeline
            schedule_details.sort()

            for effective_start, effective_end, stream, repetition in schedule_details:
                start_pos = int(effective_start * scale)
                end_pos = int(effective_end * scale)

                # Ensure positions are within bounds and length is at least 1
                start_pos = max(0, min(start_pos, timeline_width))
                end_pos = max(
                    start_pos, min(end_pos, timeline_width + 1)
                )  # Ensure end >= start
                length = max(
                    1, end_pos - start_pos
                )  # Ensure length is at least 1 if end > start

                line = " " * start_pos + "#" * length
                line = line.ljust(timeline_width + 1)  # Pad to full width

                print(f"{line} Stream {stream}, Rep {repetition}")

    def calculate_blocked_ranges(self, port, variable_length):
        """
        Calculate blocked time ranges at a specific port based on fixed streams using that port.

        A blocked range is a time interval where a variable stream of length `variable_length`
        cannot be scheduled without overlapping a fixed stream or fitting into a gap smaller than `variable_length`.

        Args:
            port: The port identifier tuple (e.g., ('0-SW1', '0-SW2'))
            variable_length: The total effective length needed for the variable stream
                             (buffering + processing + deviation*gamma).

        Returns:
            List of tuples: [(start_time, duration), ...] for each blocked range, sorted by start time.
        """
        # Get all fixed streams scheduled at this port
        fixed_schedule_at_port = self.get_fixed_stream_port_schedule(port)

        if not fixed_schedule_at_port:
            return []  # No fixed streams, so no blocked ranges

        # Create expanded schedule with each fixed stream's effective start and end times
        expanded_schedule = []
        for start_time, stream, path, rep, port_used in fixed_schedule_at_port:
            # Calculate buffering time for this fixed stream
            bp = self.datafactory.stream_dict[stream][path]["bp"].get(
                self.datafactory.get_previous_port(stream, path, port_used), 0
            )

            # Calculate processing time (including deviation)
            proc_time = self.datafactory.get_time_for_stream_port(
                stream, path, port_used
            )
            dev = self.datafactory.get_deviation_for_stream_port(
                stream, path, port_used
            )
            gamma = self.datafactory.stream_dict[stream][path]["gamma"].get(
                port_used, 1.0
            )
            total_proc_time = proc_time + dev * gamma

            # Effective start and end times including buffer
            effective_start = start_time - bp
            effective_end = start_time + total_proc_time

            expanded_schedule.append((effective_start, effective_end))

        # Sort by effective start time
        expanded_schedule.sort()

        # Merge overlapping or close ranges based on variable_length
        if not expanded_schedule:
            return []  # Should not happen if fixed_schedule_at_port was not empty

        blocked_ranges = []
        current_start, current_end = expanded_schedule[0]

        for next_start, next_end in expanded_schedule[1:]:
            gap_size = next_start - current_end

            # Check if the gap is smaller than the length needed by the variable stream (with tolerance)
            if gap_size < variable_length - 1e-9:  # Use epsilon
                # Gap is too small, merge this block with the current one
                current_end = max(current_end, next_end)
            else:
                # Gap is large enough, finish the current blocked range and start a new one
                duration = current_end - current_start
                if duration > 1e-9:  # Avoid zero-duration blocks (use epsilon)
                    blocked_ranges.append((current_start, duration))
                current_start, current_end = next_start, next_end

        # Add the final blocked range
        duration = current_end - current_start
        if duration > 1e-9:  # Use epsilon
            blocked_ranges.append((current_start, duration))

        return blocked_ranges

    def calculate_blocked_ranges_hd(self, fixed_schedule_tuples, variable_length):
        """
        Helper to calculate blocked ranges specifically for half-duplex constraints.
        Takes a list of tuples representing the schedule of fixed streams in one direction.

        Args:
            fixed_schedule_tuples: List of (start_time, stream, path, rep, port_used)
                                   for fixed streams using the device in the *opposite* direction.
            variable_length: The total effective length needed for the variable stream
                             (buffering + processing + deviation*gamma).

        Returns:
            List of tuples: [(start_time, duration), ...] for each blocked range.
        """
        if not fixed_schedule_tuples:
            return []

        # Create expanded schedule with effective start/end times for fixed streams
        expanded_schedule = []
        for start_time, stream, path, rep, port_used in fixed_schedule_tuples:
            # Use .get with default 0 for safety
            bp = self.datafactory.stream_dict[stream][path]["bp"].get(
                self.datafactory.get_previous_port(stream, path, port_used), 0
            )
            proc_time = self.datafactory.get_time_for_stream_port(
                stream, path, port_used
            )
            dev = self.datafactory.get_deviation_for_stream_port(
                stream, path, port_used
            )
            # Use .get with default 1.0 for safety
            gamma = self.datafactory.stream_dict[stream][path]["gamma"].get(
                port_used, 1.0
            )
            total_proc_time = proc_time + dev * gamma
            effective_start = start_time - bp
            effective_end = start_time + total_proc_time
            # Add a small buffer to the end time to prevent edge cases with floating point numbers
            # This ensures that if a variable stream starts *exactly* at the effective_end, it's allowed.
            # The merging logic handles cases where the gap is truly too small.
            expanded_schedule.append(
                (effective_start, effective_end + 1e-9)
            )  # Add epsilon to end

        # Sort by effective start time
        expanded_schedule.sort()

        # Merge overlapping or close ranges based on variable_length
        if not expanded_schedule:
            return []  # Should not happen if fixed_schedule_tuples was not empty

        blocked_ranges = []
        # Handle the case of a single fixed stream
        if len(expanded_schedule) == 1:
            current_start, current_end = expanded_schedule[0]
            duration = current_end - current_start
            if duration > 1e-9:  # Use epsilon
                blocked_ranges.append((current_start, duration))
            return blocked_ranges

        # Process multiple fixed streams
        current_start, current_end = expanded_schedule[0]

        for next_start, next_end in expanded_schedule[1:]:
            gap_size = next_start - current_end

            # Check if the gap is smaller than the length needed by the variable stream (with tolerance)
            # If gap_size < variable_length, the variable stream cannot fit in the gap.
            if gap_size < variable_length - 1e-9:  # Use epsilon for comparison
                # Gap is too small, merge this block with the current one by extending the end time
                current_end = max(current_end, next_end)
            else:
                # Gap is large enough. Finalize the current blocked range (if significant)
                # and start a new one.
                duration = current_end - current_start
                if duration > 1e-9:  # Avoid zero-duration blocks (use epsilon)
                    blocked_ranges.append((current_start, duration))
                # Start the new blocked range
                current_start, current_end = next_start, next_end

        # Add the final blocked range after the loop finishes
        duration = current_end - current_start
        if duration > 1e-9:  # Use epsilon
            blocked_ranges.append((current_start, duration))

        return blocked_ranges


# End of OptimizationModel class
