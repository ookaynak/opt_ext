import math


class DataFactory:
    """
    Provides functions for working with streams and their associated ports.
    """

    def __init__(self, stream_dict):
        self.stream_dict = stream_dict
        self.streams = self.stream_dict.keys()
        self.M = 9999999
        self.lcm_rep = 1
        self.lcm = self._calculate_lcm(
            [
                self.stream_dict[stream][path]["period"]
                for stream in self.stream_dict
                for path in self.stream_dict[stream]
            ]
        )

        self.stream_dict

        for stream in self.stream_dict:
            for path in self.stream_dict[stream]:
                period = self.stream_dict[stream][path]["period"]
                (
                    self.stream_dict[stream][path]["last_rep_index"],
                    self.stream_dict[stream][path]["repetitions"],
                ) = self._calculate_repetitions_list(period, self.lcm, self.lcm_rep)

        self.ports = set()
        for stream_key in self.stream_dict:
            for path in self.stream_dict[stream_key].values():
                self.ports.update(path["ports"])

    @staticmethod
    def _calculate_lcm(numbers: list):
        lcm_result = 1
        for num in numbers:
            lcm_result = math.lcm(lcm_result, num)
        print(lcm_result)
        return lcm_result

    @staticmethod
    def _calculate_repetitions_list(period_s: int, lcm: int, lcm_rep: int):
        repetition_length = int(lcm / period_s)
        last_rep_index = repetition_length - 1
        virtual_repetition_length = lcm_rep * repetition_length

        # Check if repetition_length is not an integer
        if repetition_length % 1 != 0:
            raise ValueError(
                f"Repetition length is not an integer: {virtual_repetition_length}"
            )

        return last_rep_index, [x for x in range(1, int(virtual_repetition_length) + 1)]

    def get_ports_for_stream(self, stream):
        if stream in self.stream_dict:
            return self.stream_dict[stream]["ports"]
        else:
            return None

    def get_next_port(self, stream, path, current_port):
        """
        Returns the next port in the sequence for the given stream and current port.
        Raises ValueError if the current port is not found in the stream's ports or if it's the last port.
        """
        ports = self.stream_dict[stream][path]["ports"]
        index = ports.index(current_port)

        return ports[index + 1]

    def get_previous_port(self, stream, path, current_port):
        """
        Returns the previous port in the sequence for the given stream and current port.
        Returns 'p0' if the current port is the first port.
        Raises ValueError if the current port is not found in the stream's ports or if it's the first port.
        """

        ports = self.stream_dict[stream][path]["ports"]
        index = ports.index(current_port)
        return ports[index - 1]

    def get_streams_for_port(self, port):
        streams_with_port = []
        for stream in self.stream_dict:
            for path in self.stream_dict[stream]:
                if port in self.stream_dict[stream][path]["ports"]:
                    streams_with_port.append(stream)
                    break
        return streams_with_port

    def get_paths_for_port_stream(self, stream, port):
        paths_with_port = []
        for path in self.stream_dict[stream]:
            if port in self.stream_dict[stream][path]["ports"]:
                paths_with_port.append(path)
        return paths_with_port

    def get_time_for_stream_port(self, stream, path, port):
        path = self.stream_dict[stream][path]
        return sum(path["times"][port].values())

    def get_deviation_for_stream_port(self, stream, path, port):
        path = self.stream_dict[stream][path]

        return sum(path["deviations"][port].values())

    def get_repetitions_for_stream(self, stream):
        if stream in self.stream_dict:
            return self.stream_dict[stream][0]["repetitions"]
        return None
