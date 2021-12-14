#!/usr/bin/env python3
#
# Copyright (c) 2019, Arista Networks EOS+
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the Arista nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"""Utilities for using PyTest in network testing"""

import concurrent.futures
import time
import fcntl
import sys
import logging
import os
import inspect
import pyeapi
import yaml


logging.basicConfig(
    level=logging.INFO,
    filename="test_tools.log",
    filemode="w",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def init_show_log(test_parameters):
    """Open log file for logging test show commands

    Args:
        test_parameters (dict): Abstraction of testing parameters
    """

    logging.info("Open log file for logging test show commands")

    if "parameters" in test_parameters:
        parameters_ptr = test_parameters["parameters"]
        if "show_log" in parameters_ptr:
            log_file = parameters_ptr["show_log"]
        else:
            print(">>>  ERROR IN DEFINITIONS FILE")
            logging.error("NO SHOW_LOG CONFIGURED IN TEST DEFs")
            logging.error("EXITING TEST RUNNER")
            sys.exit(1)
    else:
        logging.error("NO PARAMETERS CONFIGURED IN TEST DEFs")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)

    logging.info(f"Opening {log_file} for write")
    try:
        with open(log_file, "w"):
            logging.info(f"Opened {log_file} for write")
    except BaseException as error:
        print(f">>>  ERROR OPENING LOG FILE: {error}")
        logging.error(f"ERROR OPENING LOG FILE: {error}")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)


def import_yaml(yaml_file):
    """Import YAML file as python data structure
    Args:
        yaml_file (str): Name of YAML file

    Returns:
        yaml_data (dict): YAML data structure
    """

    logging.info(f"Opening {yaml_file} for read")
    try:
        with open(yaml_file, "r") as input_yaml:
            try:
                yaml_data = yaml.safe_load(input_yaml)
                logging.info(f"Inputed the following yaml: " f"{yaml_data}")
                return yaml_data
            except yaml.YAMLError as err:
                print(">>> ERROR IN YAML FILE")
                logging.error(f"ERROR IN YAML FILE: {err}")
                logging.error("EXITING TEST RUNNER")
                sys.exit(1)
    except OSError as err:
        print(">>> YAML FILE MISSING")
        logging.error(f"ERROR YAML FILE: {yaml_file} NOT " f"FOUND. {err}")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)
    sys.exit(1)


def return_dut_list(test_parameters):
    """test_parameters to create a duts_list for a list of ids
    that will identify individual test runs

    Args:
        test_parameters (dict): Abstraction of testing parameters

    Returns:
        duts (list): List of DUT hostnames
    """

    logging.info("Creating a list of duts from test defintions")
    if "duts" in test_parameters:
        logging.info("Duts configured in test defintions")
        duts = [dut["name"] for dut in test_parameters["duts"]]
    else:
        print(">>> NO DUTS CONFIGURED")
        logging.error("NO DUTS CONFIGURED")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)

    logging.info(f"Returning duts: {duts}")
    return duts


def init_duts(show_cmds, test_parameters):
    """Use PS LLD spreadsheet to find interesting duts and then execute
    inputted show commands on each dut.  Return structured data of
    dut's output data, hostname, and connection.  Using threading to
    make method more efficent.

    Args:
      show_cmds (str): list of interesting show commands
      test_parameters (dict): Abstraction of testing parameters
      test_suite (str): test suite name

    return:
      duts (dict): structured data of duts output data, hostname, and
                   connection
    """

    logging.info(
        "Finding DUTs and then execute inputted show commands "
        "on each dut.  Return structured data of DUTs output "
        "data, hostname, and connection."
    )
    duts = login_duts(test_parameters)
    workers = len(duts)
    logging.info(f"Duts login info: {duts} and create {workers} workers")
    logging.info(f"Passing the following show commands to workers: {show_cmds}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        {
            executor.submit(dut_worker, dut, show_cmds, test_parameters): dut
            for dut in duts
        }

    logging.info(f"Return duts data structure: {duts}")
    return duts


def login_duts(test_parameters):
    """Use eapi to connect to Arista switches for testing

    Args:
      test_parameters (dict): Abstraction of testing parameters

    return:
      logins (list): List of dictionaries with connection and name
                     of DUTs
    """

    logging.info("Using eapi to connect to Arista switches for testing")
    duts = test_parameters["duts"]
    logins = []
    pyeapi.load_config(test_parameters["parameters"]["eapi_file"])
    for dut in duts:
        name = dut["name"]
        login_index = len(logins)
        logins.append({})
        login_ptr = logins[login_index]
        logging.info(f"Connecting to switch: {name} using parameters: {dut}")
        login_ptr["connection"] = pyeapi.connect_to(name)
        login_ptr["name"] = name
        login_ptr["mgmt_ip"] = dut["mgmt_ip"]
        login_ptr["username"] = dut["username"]
        
    logging.info(f"Returning duts logins: {logins}")
    return logins


def send_cmds(show_cmds, conn, encoding):
    """Send show commands to duts and recurse on failure

    Args:
        show_cmds (list): List of pre-process commands
        conn (obj): connection
    """

    logging.info(f"In send_cmds")
    try:
        logging.info(
            f"List of show commands in show_cmds with encoding {encoding}: {show_cmds}"
        )
        if encoding == "json":
            show_cmd_list = conn.run_commands(show_cmds)
        elif encoding == "text":
            show_cmd_list = conn.run_commands(show_cmds, encoding="text")
        logging.info(f"ran all show cmds with encoding {encoding}: {show_cmds}")

    except Exception as e:
        logging.error(f"error running all cmds: {e}")
        show_cmds = remove_cmd(e, show_cmds)
        logging.info(f"new show_cmds: {show_cmds}")
        show_cmd_list = send_cmds(show_cmds, conn, encoding)
        show_cmd_list = show_cmd_list[0]

    logging.info(f"return all show cmds: {show_cmd_list}")
    return show_cmd_list, show_cmds


def remove_cmd(e, show_cmds):
    """Remove command that is not supported by pyeapi

    Args:
        e (str): Error string
        show_cmds (list): List of pre-process commands
    """

    logging.info(f"remove_cmd: {e}")
    logging.info(f"remove_cmd show_cmds list: {show_cmds}")
    for show_cmd in show_cmds:
        if show_cmd in str(e):
            cmd_index = show_cmds.index(show_cmd)
            show_cmds.pop(cmd_index)

    return show_cmds


def dut_worker(dut, show_cmds, test_parameters):
    """Execute inputted show commands on dut.  Update dut structured data
    with show output.

    Args:
      dut (dict): structured data of a dut output data, hostname, and
      connection test_suite (str): test suite name
    """

    name = dut["name"]
    conn = dut["connection"]
    dut["output"] = {}
    dut["output"]["interface_list"] = return_interfaces(name, test_parameters)

    logging.info(f"Executing show commands on {name}")
    logging.info(f"List of show commands {show_cmds}")
    logging.info(f"Number of show commands {len(show_cmds)}")

    all_cmds_json = show_cmds.copy()
    show_cmd_json_list, show_cmds_json = send_cmds(all_cmds_json, conn, "json")
    logging.info(f"Returned from send_cmds_json {show_cmds_json}")

    all_cmds_txt = show_cmds.copy()
    show_cmd_txt_list, show_cmds_txt = send_cmds(all_cmds_txt, conn, "text")
    logging.info(f"Returned from send_cmds_txt {show_cmds_txt}")

    for show_cmd in show_cmds:
        function_def = f'test_{("_").join(show_cmd.split())}'
        logging.info(
            f"Executing show command: {show_cmd} for test " f"{function_def}"
        )

        logging.info(f"Adding output of {show_cmd} to duts data structure")
        dut["output"][show_cmd] = {}

        if show_cmd in show_cmds_json:
            cmd_index = show_cmds_json.index(show_cmd)
            logging.info(
                f"found cmd: {show_cmd} at index {cmd_index} of {show_cmds_json}"
            )
            logging.info(
                f"length of cmds: {len(show_cmds_json)} vs length of output {len(show_cmd_json_list)}"
            )
            show_output = show_cmd_json_list[cmd_index]
            dut["output"][show_cmd]["json"] = show_output
            logging.info(f"Adding cmd {show_cmd} to dut and data {show_output}")
        else:
            dut["output"][show_cmd]["json"] = ""
            logging.info(f"No json output for {show_cmd}")

        if show_cmd in show_cmds_txt:
            cmd_index = show_cmds_txt.index(show_cmd)
            show_output_txt = show_cmd_txt_list[cmd_index]
            dut["output"][show_cmd]["text"] = show_output_txt["output"]
            logging.warning(
                f"Adding text cmd {show_cmd} to dut and data {show_output_txt}"
            )
        else:
            dut["output"][show_cmd]["text"] = ""
            logging.warning(f"No text output for {show_cmd}")

    logging.info(f"{name} updated with show output {dut}")


def return_show_cmd(show_cmd, dut, test_name, test_parameters):
    """Return model data and text output from show commands and log text output.

    Args:
      show_cmd (str): show command
      dut (dict): Dictionary containing dut name and connection
      test_name (str): test case name

    return:
      show_output (dict): json output of cli command
      show_output (dict): plain-text output of cli command
    """

    logging.info(
        f"Raw Input for return_show_cmd \nshow_cmd: {show_cmd}\ndut: "
        f"{dut} \ntest_name: {test_name} \ntest_parameters: "
        f"{test_parameters}"
    )
    conn = dut["connection"]
    name = dut["name"]
    logging.info(
        "Return model data and text output from show commands and "
        f"log text output for {show_cmd} with connnection {conn}"
    )

    show_output = conn.enable(show_cmd)
    logging.info(f"Raw json output of {show_cmd} on dut {name}: {show_output}")

    try:
        show_output_text = conn.run_commands(show_cmd, encoding="text")
        raw_text = show_output_text[0]["output"]
    except Exception as e:
        logging.error(f"Missed on commmand {show_cmd}")
        logging.error(f"Error msg {e}")
        time.sleep(1)
        show_output_text = conn.run_commands(show_cmd, encoding="text")
        logging.error(f"new value of show_output_text  {show_output_text}")
        raw_text = show_output_text[0]["output"]
    logging.info(
        f"Raw text output of {show_cmd} on dut {name}: " f"{show_output_text}"
    )

    export_logs(test_name, name, raw_text, test_parameters)

    return show_output, show_output_text


def return_interfaces(hostname, test_parameters):
    """parse test_parameters for interface connections and return them to test

    Args:
        dut_name (str):      hostname of dut
        xlsx_workbook (obj): Abstraction of spreadsheet,

    return:
      interface_list (list): list of interesting interfaces based on
                             PS LLD spreadsheet
    """

    logging.info(
        "Parse test_parameters for interface connections and return "
        "them to test"
    )
    interface_list = []
    duts = test_parameters["duts"]

    for dut in duts:
        dut_name = dut["name"]

        if dut_name == hostname:
            logging.info(f"Discovering interface parameters for: {hostname}")
            neighbors = dut["neighbors"]

            for neighbor in neighbors:
                interface = {}
                logging.info(
                    f"Adding interface parameters: {neighbor} "
                    f"neighbor for: {dut_name}"
                )

                interface["hostname"] = dut_name
                interface["interface_name"] = neighbor["port"]
                interface["z_hostname"] = neighbor["neighborDevice"]
                interface["z_interface_name"] = neighbor["neighborPort"]
                interface["media_type"] = ""
                interface_list.append(interface)

    logging.info(f"Returning interface list: {interface_list}")
    return interface_list


def export_logs(test_name, hostname, output, test_parameters):
    """Open log file for logging test show commands

    Args:
      LOG_FILE (str): path and name of log file
    """

    logging.info("Open log file for logging test show commands")
    show_log = test_parameters["parameters"]["show_log"]

    try:
        logging.info(
            f"Opening file {show_log} and append show output: " f"{output}"
        )
        with open(show_log, "a") as log_file:
            log_file.write(f"\ntest_suite::{test_name}[{hostname}]:\n{output}")
    except BaseException as error:
        print(f">>>  ERROR OPENING LOG FILE: {error}")
        logging.error(f"ERROR OPENING LOG FILE: {error}")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)


def get_parameters(tests_parameters, test_suite, test_case=""):
    """Return test parameters for a test case

    Args:
        tests_parameter
    """

    if not test_case:
        test_case = inspect.stack()[1][3]
        logging.info(f"Setting testcase name to {test_case}")

    logging.info("Identify test case and return parameters")
    test_suite = test_suite.split("/")[-1]

    logging.info(f"Return testcases for Test Suite: {test_suite}")
    suite_parameters = [
        param
        for param in tests_parameters["test_suites"]
        if param["name"] == test_suite
    ]
    logging.info(f"Suite_parameters: {suite_parameters}")

    logging.info(f"Return parameters for Test Case: {test_case}")
    case_parameters = [
        param
        for param in suite_parameters[0]["testcases"]
        if param["name"] == test_case
    ]
    logging.info(f"Case_parameters: {case_parameters[0]}")

    case_parameters[0]["test_suite"] = test_suite

    return case_parameters[0]


def verify_show_cmd(show_cmd, dut):
    """Verify if show command was successfully executed on dut

    show_cmd (str): show command
    dut (dict): data structure of dut parameters
    """

    dut_name = dut["name"]
    logging.info(
        f"Verify if show command |{show_cmd}| was successfully "
        f"executed on {dut_name} dut"
    )

    if show_cmd in dut["output"]:
        logging.info(
            f"Verified output for show command |{show_cmd}| on " f"{dut_name}"
        )
    else:
        logging.critical(
            f"Show command |{show_cmd}| not executed on " f"{dut_name}"
        )
        assert False


def verify_tacacs(dut):
    """Verify if tacacs servers are configured

    dut (dict): data structure of dut parameters
    """

    dut_name = dut["name"]
    show_cmd = "show tacacs"

    tacacs_bool = True
    tacacs = dut["output"][show_cmd]["json"]["tacacsServers"]
    tacacs_servers = len(tacacs)
    logging.info(
        f"Verify if tacacs server(s) are configured " f"on {dut_name} dut"
    )

    if tacacs_servers == 0:
        tacacs_bool = False

    logging.info(
        f"{tacacs_servers} tacacs serverws are configured so "
        f"returning {tacacs_bool}"
    )

    return tacacs_bool


def verify_veos(dut):
    """Verify DUT is a VEOS instance

    dut (dict): data structure of dut parameters
    """

    dut_name = dut["name"]
    show_cmd = "show version"

    veos_bool = False
    veos = dut["output"][show_cmd]["json"]["modelName"]
    logging.info(
        f"Verify if {dut_name} DUT is a VEOS instance. " f"Model is {veos}"
    )

    if veos == "vEOS":
        veos_bool = True
        logging.info(f"{dut_name} is a VEOS instance so returning {veos_bool}")
        logging.info(f"{dut_name} is a VEOS instance so test NOT valid")
    else:
        logging.info(
            f"{dut_name} is not a VEOS instance so returning " f"{veos_bool}"
        )

    return veos_bool


def generate_interface_list(dut_name, test_definition):
    """test_definition is used to createa a interface_list for active
    DUT interfaces and attributes

    Returns:
        interface_list (list): list of active DUT interfaces and attributes
    """

    dut_hostnames = [dut["name"] for dut in test_definition["duts"]]
    dut_index = dut_hostnames.index(dut_name)
    int_ptr = test_definition["duts"][dut_index]
    interface_list = int_ptr["test_criteria"][0]["criteria"]

    return interface_list


def yaml_io(yaml_file, io_type, yaml_data=None):
    """Write test results to YAML file for post-processing

    Args:
        yaml_file (str): Name of YAML file
        io (str): Read or write to YAML file
    """

    while True:
        try:
            if io_type == "read":
                with open(yaml_file, "r") as yaml_in:
                    fcntl.flock(yaml_in, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    yaml_data = yaml.safe_load(yaml_in)
                    break
            else:
                with open(yaml_file, "w") as yaml_out:
                    yaml.dump(yaml_data, yaml_out, default_flow_style=False)
                    fcntl.flock(yaml_out, fcntl.LOCK_UN)
                    break
        except:
            time.sleep(0.05)

    return yaml_data


def return_show_cmds(test_parameters):
    """Return show commands from the test_defintions

    Args:
        test_parameters (dict): Input DUT test definitions
    """

    show_cmds = []

    logging.info(f"Discover the names of test suites from {test_parameters}")
    test_data = test_parameters["test_suites"]
    test_suites = [param["name"] for param in test_data]

    for test_suite in test_suites:
        test_index = test_suites.index(test_suite)
        test_cases = test_data[test_index]["testcases"]
        logging.info(f"Find show commands in test suite: {test_suite}")

        for test_case in test_cases:
            show_cmd = test_case["show_cmd"]
            logging.info(f"Found show command {show_cmd}")

            if show_cmd not in show_cmds and show_cmd is not None:
                logging.info(f"Adding Show command {show_cmd}")
                show_cmds.append(show_cmd)

    logging.info(
        "The following show commands are required for test cases: "
        f"{show_cmds}"
    )
    return show_cmds


def return_test_defs(test_parameters):
    """Return show commands from the test_defintions

    Args:
        def_file (test_parameters): Name of definitions file
    """

    test_defs = {"test_suites": []}
    test_dir = test_parameters["parameters"]["tests_dir"]
    for test_directory in test_dir:
        tests_info = os.walk(test_directory)
        for dir_path, _ , file_names in tests_info:
            for file_name in file_names:
                if file_name == "test_definition.yaml":
                    file_path = f"{dir_path}/{file_name}"
                    test_def = import_yaml(file_path)
                    test_defs["test_suites"].append(test_def)
    
    export_yaml("../reports/tests_definitions.yaml", test_defs)
    logging.info(
        "Return the following test definitions data strcuture " f"{test_defs}"
    )

    return test_defs


def export_yaml(yaml_file, yaml_data):
    """Export python data structure as a YAML file

    Args:
        yaml_file (str): Name of YAML file
    """

    logging.info(f"Opening {yaml_file} for write")
    try:
        with open(yaml_file, "w") as yaml_out:
            try:
                logging.info(f"Output the following yaml: " f"{yaml_data}")
                yaml.dump(yaml_data, yaml_out, default_flow_style=False)
            except yaml.YAMLError as err:
                print(">>> ERROR IN YAML FILE")
                logging.error(f"ERROR IN YAML FILE: {err}")
                logging.error("EXITING TEST RUNNER")
                sys.exit(1)
    except OSError as err:
        print(">>> YAML FILE MISSING")
        logging.error(f"ERROR YAML FILE: {yaml_file} NOT " f"FOUND. {err}")
        logging.error("EXITING TEST RUNNER")
        sys.exit(1)


class TestOps:
    """Common testcase operations and variables"""

    def __init__(self, tests_definitions, test_suite, dut):
        """Initializes TestOps Object

        Args:
            test_definition (str): YAML representation of NRFU tests
        """

        test_case = inspect.stack()[1][3]
        self.test_case = test_case
        self.test_parameters = self._get_parameters(
            tests_definitions, test_suite, self.test_case
        )

        self.expected_output = self.test_parameters["expected_output"]

        self.interface_list = dut["output"]["interface_list"]
        self.dut_name = dut["name"]
        self.show_cmd = self.test_parameters["show_cmd"]
        self.dut = dut

        if self.show_cmd:
            self._verify_show_cmd(self.show_cmd, dut)
            self.show_cmd_txt = dut["output"][self.show_cmd]["text"]
        else:
            self.show_cmd_txt = ""

        self.comment = ""
        self.output_msg = ""
        self.actual_results = []
        self.expected_results = []

    def _verify_show_cmd(self, show_cmd, dut):
        """Verify if show command was successfully executed on dut

        show_cmd (str): show command
        dut (dict): data structure of dut parameters
        """

        dut_name = dut["name"]
        logging.info(
            f"Verify if show command |{show_cmd}| was successfully "
            f"executed on {dut_name} dut"
        )

        if show_cmd in dut["output"]:
            logging.info(
                f"Verified output for show command |{show_cmd}| on "
                f"{dut_name}"
            )
        else:
            logging.critical(
                f"Show command |{show_cmd}| not executed on " f"{dut_name}"
            )
            assert False

    def post_testcase(self):
        """Do post processing for test case"""

        self.test_parameters["comment"] = self.comment
        self.test_parameters["test_result"] = self.test_result
        self.test_parameters["output_msg"] = self.output_msg
        self.test_parameters["expected_output"] = self.expected_output
        self.test_parameters["actual_output"] = self.actual_output
        self.test_parameters["dut"] = self.dut_name

        self.test_parameters["fail_reason"] = ""
        if not self.test_parameters["test_result"]:
            self.test_parameters["fail_reason"] = self.output_msg

        self._write_results()

    def _write_results(self):
        """"""

        logging.info(f"Preparing to write results")
        test_suite = self.test_parameters["test_suite"]
        test_suite = test_suite.split("/")[-1]
        dut_name = self.test_parameters["dut"]
        test_case = self.test_parameters["name"]

        yaml_file = f"../reports/results/result-{test_case}-{dut_name}.yml"
        logging.info(f"Creating results file named {yaml_file}")

        yaml_data = self.test_parameters
        export_yaml(yaml_file, yaml_data)

    def _get_parameters(self, tests_parameters, test_suite, test_case):
        """Return test parameters for a test case

        Args:
            tests_parameter
        """

        if not test_case:
            test_case = inspect.stack()[1][3]
            logging.info(f"Setting testcase name to {test_case}")

        logging.info("Identify test case and return parameters")
        test_suite = test_suite.split("/")[-1]

        logging.info(f"Return testcases for Test Suite: {test_suite}")
        suite_parameters = [
            param
            for param in tests_parameters["test_suites"]
            if param["name"] == test_suite
        ]
        logging.info(f"Suite_parameters: {suite_parameters}")

        logging.info(f"Return parameters for Test Case: {test_case}")
        case_parameters = [
            param
            for param in suite_parameters[0]["testcases"]
            if param["name"] == test_case
        ]
        logging.info(f"Case_parameters: {case_parameters[0]}")

        case_parameters[0]["test_suite"] = test_suite

        return case_parameters[0]

    def return_show_cmd(self, show_cmd):
        """Return model data and text output from show commands and log text output.

        Args:
          show_cmd (str): show command
        """

        self.show_cmd = show_cmd
        logging.info(f"Raw Input for return_show_cmd \nshow_cmd: {show_cmd}\n")
        conn = self.dut["connection"]
        name = self.dut["name"]
        logging.info(
            "Return model data and text output from show commands and "
            f"log text output for {show_cmd} with connnection {conn}"
        )

        show_output = conn.enable(show_cmd)
        self.show_output = show_output[0]["result"]
        logging.info(
            f"Raw json output of {show_cmd} on dut {name}: {self.show_output}"
        )

        show_output_text = conn.run_commands(show_cmd, encoding="text")
        logging.info(
            f"Raw text output of {show_cmd} on dut {name}: "
            f"{self.show_cmd_txt}"
        )
        self.show_cmd_txt = show_output_text[0]["output"]

        return self.show_output, self.show_cmd_txt

    def verify_veos(self):
        """Verify DUT is a VEOS instance"""

        show_cmd = "show version"

        veos_bool = False
        veos = self.dut["output"][show_cmd]["json"]["modelName"]
        logging.info(
            f"Verify if {self.dut_name} DUT is a VEOS instance. "
            f"Model is {veos}"
        )

        if veos == "vEOS":
            veos_bool = True
            logging.info(
                f"{self.dut_name} is a VEOS instance so returning {veos_bool}"
            )
        else:
            logging.info(
                f"{self.dut_name} is not a VEOS instance so returning "
                f"{veos_bool}"
            )

        return veos_bool
