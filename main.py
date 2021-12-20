"""
Copyright 2021 Fabian H. Schneider

This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file,
You can obtain one at https://mozilla.org/MPL/2.0/.
"""
import os
import sys
import time
from concurrent import futures

import colorama

import settings
from appveyor.appveyor_app import AppveyorApp
from config_handler.config_handler import ConfigHandler
from config_handler.eula import EulaChecker
from environment_handler.environment_handler import LockFile, LockFileException
from file_handler.file_handler import FileHandler
from generic_app.generic_app import GenericApp
from generic_app.generic_manager import GenericManager
from github.github_app import GithubApp
from helper.terminal import BRIGHT, CYAN, GREEN, MAGENTA, RED, RESET, print_header
from html_seu.html_app import HTMLApp

TRIGGER_UPDATE_STATUS = ("update", "no_version_file", "not_installed")


class Main:
    def __init__(self):
        try:
            self.__lock = LockFile()
        except LockFileException:
            time.sleep(7)
            sys.exit()
        EulaChecker.check_eula()
        # Configuration
        ConfigHandler()
        self.cfg_auth = settings.app_config["auth"]
        self.cfg_available = settings.app_config["available"]
        self.cfg_local = settings.app_config["local"]
        self.__multithreaded = True
        # Helper objects
        self.job_list = []

    def execute(self):
        """
        The execute() methods in the project are supposed to provide an idea of what the class does in a nutshell.
        Always put them directly after __init__().
        """
        self.__check_updates()
        self.__update_apps()
        FileHandler.pre_exit_cleanup(self.cfg_local)
        self.__lock.__del__()
        input("Press Enter to continue...")

    def __check_updates(self):
        project_list = []
        for path in self.cfg_local:
            native_path = FileHandler.make_path_native(path)
            for list_item in self.cfg_local[path]:
                if list_item.casefold() in self.cfg_available:
                    appconf = self.cfg_available[list_item.casefold()]
                    if appconf["repo"]:
                        job = None
                        if appconf["repo"] == "appveyor":
                            job = AppveyorApp(native_path, **appconf)
                        elif appconf["repo"] == "github":
                            job = GithubApp(native_path, **appconf)
                        elif appconf["repo"] == "html":
                            job = HTMLApp(native_path, **appconf)
                        if job is not None:
                            project_list.append(job)

        if self.__multithreaded:
            with futures.ThreadPoolExecutor(max_workers=8) as executor:
                projects = {
                    executor.submit(Main.__threadable_update_check, project): project for project in project_list
                }
                for appconf in futures.as_completed(projects):
                    if projects[appconf].update_status in TRIGGER_UPDATE_STATUS:
                        self.job_list.append(projects[appconf])
        else:
            for appconf in project_list:
                Main.__threadable_update_check(appconf)
                if appconf.update_status in TRIGGER_UPDATE_STATUS:
                    self.job_list.append(appconf)

    @staticmethod
    def __threadable_update_check(project):
        project.execute()
        GenericManager.check_update(project)
        Main.project_status_report(project)

    def __update_apps(self):
        for job in self.job_list:
            my_fsm = FileHandler(job)
            message = f"{job.name}: "
            if job.update_status == "update":
                message += "Updating"
                print_header(message, GREEN)
                my_fsm.project_update()
            elif job.update_status == "no_version_file":
                message += "Updating (forced)"
                print_header(message, MAGENTA)
                my_fsm.project_update()
            elif job.update_status == "not_installed":
                message += "Installing"
                print_header(message, CYAN)
                my_fsm.project_install()

    @staticmethod
    def project_status_report(project: GenericApp):
        color = ""
        message = ""
        if project.update_status == "no_update":
            color = BRIGHT
            message = "No update available"
        elif project.update_status == "installed_newer":
            color = MAGENTA
            message = (
                "Installed is newer.\r\n "
                + RESET
                + project.name
                + ": Please make sure your version wasn't retracted because of problems with it."
            )
        elif project.update_status == "update":
            color = GREEN
            message = "Update available"
        elif project.update_status == "no_version_file":
            color = MAGENTA
            message = "Update forced (no valid version info found)"
        elif project.update_status == "not_installed":
            color = CYAN
            message = "Will be installed"
        elif project.update_status == "error":
            color = RED
            message = "Could not determine the version installed"
        elif project.update_status == "failed":
            color = RED
            message = "Could not connect to URL or API"
        elif project.update_status == "unknown":
            color = RED
            message = "Failed to check this project"
        print("%s%s: %s\r\n%s" % (color, project.name, message, RESET), end="")

    @staticmethod
    def color_handling(init=True):
        if init:
            os.system("cls")
            os.system("color 0f")
            colorama.init()
            print(colorama.Back.BLACK, end="")
            print(colorama.Fore.WHITE, end="")
        else:
            os.system("color")
            print(colorama.Style.RESET_ALL, end="")
            os.system("cls")


if __name__ == "__main__":
    Main.color_handling()
    superelixier_updater = Main()
    superelixier_updater.execute()
    Main.color_handling(init=False)
