################################################################################
#
#  Copyright 2014-2015 Eric Lacombe <eric.lacombe@security-labs.org>
#
################################################################################
#
#  This file is part of fuddly.
#
#  fuddly is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  fuddly is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with fuddly. If not, see <http://www.gnu.org/licenses/>
#
################################################################################

import subprocess
import signal
import select
import fcntl
import os
import random

from fuzzfmk.plumbing import *
from fuzzfmk.target import *
from fuzzfmk.logger import *

from fuzzfmk.data_model import *
from fuzzfmk.tactics_helper import *
from fuzzfmk.fuzzing_primitives import *

tactics = Tactics()

logger = Logger('jpg', data_in_seperate_file=True, explicit_export=True, export_orig=False)

printer1_tg = PrinterTarget(tmpfile_ext='.jpg')
printer1_tg.set_target_ip('127.0.0.1')
printer1_tg.set_printer_name('PDF')

local_tg = LocalTarget(tmpfile_ext='.jpg')
local_tg.set_target_path('display')

printer2_tg = PrinterTarget(tmpfile_ext='.jpg')
printer2_tg.set_target_ip('172.20.130.1')

targets = [local_tg, printer1_tg, printer2_tg]


@blocking_probe(tactics)
class health_check(Probe):

    def start(self, target, logger):
        self.status = ProbeStatus(0)

    def stop(self, target, logger):
        pass

    def main(self, target, logger):
        fb = target.get_target_feedback()
        byte_string = fb.get_bytes()
        self.status.set_private_info(byte_string)
        self.status.set_status(0)

        if target.is_damaged():
            self.status.set_status(-1)

        if not target.is_alive():
            self.status.set_status(-2)

        return self.status


@operator(tactics,
          gen_args={'init': ('make the model walker ignore all the steps until the provided one', 1, int),
                    'max_steps': ("number of test cases to run", 20, int)},
          args={'mode': ('strategy mode (0 or 1)', 0, int),
                'path': ("path of the target application (for LocalTarget's only)", '/usr/bin/display', str)})
class Op1(Operator):

    def start(self, fmk_ops, dm, monitor, target, logger, user_input):

        if isinstance(target, LocalTarget):
            target.set_target_path(self.path)

        self.nb_gen_val_cpt = 0
        if self.mode == 1:
            self.nb_gen_val_cpt = self.max_steps // 2
            self.max_steps = self.max_steps - self.nb_gen_val_cpt

        self.gen_ids = []
        for gid in fmk_ops.dynamic_generator_ids():
            self.gen_ids.append(gid)
        print('\n*** Data IDs found: ', self.gen_ids)
        self.init_gen_len = len(self.gen_ids)
        self.current_gen_id = self.gen_ids.pop(0)

        if isinstance(target, LocalTarget):
            monitor.start_probe('health_check')

        # fmk_ops.set_fuzz_delay(5)
        return True

    def stop(self, fmk_ops, dm, monitor, target, logger):
        if isinstance(target, LocalTarget):
            monitor.stop_probe('health_check')


    def plan_next_operation(self, fmk_ops, dm, monitor, target, logger, fmk_feedback):

        op = Operation()

        if self.max_steps > 0:
            
            if fmk_feedback.is_flag_set(FmkFeedback.NeedChange):
                try:
                    self.current_gen_id = self.gen_ids.pop(0)
                    op.set_flag(Operation.CleanupDMakers)
                except IndexError:
                    op.set_flag(Operation.Stop)
                    return op

                change_list = fmk_feedback.get_flag_context(FmkFeedback.NeedChange)
                for dmaker, idx in change_list:
                    logger.log_fmk_info('Exhausted data maker [#{:d}]: {:s} ({:s})'.format(idx, dmaker['dmaker_type'], dmaker['dmaker_name']),
                                        nl_before=True, nl_after=False)
                time.sleep(1)


            clone_tag = "#{:d}".format(len(self.gen_ids) + 1)
            clone_tag2 = "#{:d}".format(self.init_gen_len + len(self.gen_ids) + 1)

            actions = [(self.current_gen_id + clone_tag, UI(finite=True)), ('tTYPE' + clone_tag, UI(init=self.init))]

            self.max_steps -= 1

        elif self.mode == 1 and self.nb_gen_val_cpt > 0:
            actions = [(self.current_gen_id + clone_tag2, UI(finite=True)), ('tTERM' + clone_tag2, UI(init=self.init))]

            self.nb_gen_val_cpt -= 1

        else:
            actions = None

        if actions:
            op.add_instruction(actions)
        else:
            op.set_flag(Operation.Stop)

        return op


    def do_after_all(self, fmk_ops, dm, monitor, target, logger):
        linst = LastInstruction()

        if isinstance(target, LocalTarget):
            health_status = monitor.get_probe_status('health_check')
            linst.set_target_feedback_info(health_status.get_private_info())

            if health_status.get_status() == -1:
                linst.set_instruction(LastInstruction.ExportData)
                linst.set_comments('This input has triggered an error, but not a crash!')
                target.stop_target()
            elif health_status.get_status() == -2:
                linst.set_instruction(LastInstruction.ExportData)
                linst.set_comments('This input has crashed the target!')
            else:
                target.stop_target()
        else:
            linst.set_instruction(LastInstruction.ExportData)
        
        return linst
