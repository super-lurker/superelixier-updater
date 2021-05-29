"""
Copyright 2021 Fabian H. Schneider

This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file,
You can obtain one at https://mozilla.org/MPL/2.0/.
"""
import colorama
import requests
import datetime
import html
import json
import os
import re
import string
import shutil
import subprocess
import sys
from urllib.parse import urlparse, urlunparse
from generic_app.generic_app import GenericApp

BIN = os.path.join(os.path.dirname(sys.argv[0]), "bin-win32")
SEVENZIP = os.path.join(BIN, "7z", "7z.exe")
INNOEXTRACT = os.path.join(BIN, "innoextract", "innoextract.exe")


class FileHandler:

    def __init__(self, app: GenericApp):
        now_string = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%dT%H.%M.%S")
        self.__app = app
        self.__cache = os.path.join(app.target_dir, ".superelixier-cache")
        self.__staging = os.path.join(self.__cache, str(app.random_id))
        self.__keep_history = True
        self.__history = os.path.join(app.appdir, ".superelixier-history", now_string)
        self.__deferred = os.path.join(self.__cache, ".deferred", app.name)

    def __project_download(self):
        """
        Handle the download of blobs or check if deferred update matches latest version on remote site.

        :return: False if the directory should be normalized, True if not.
        """
        # Check if deferred update files should be leveraged
        version_deferred = os.path.join(self.__deferred, "superelixier.json")
        if os.path.isfile(version_deferred):
            with open(version_deferred, 'r') as file:
                version_deferred = json.load(file)
            if version_deferred == self.__app.version_latest:
                print(colorama.Fore.GREEN + self.__app.name + ": Re-using previously downloaded update files")
                self.__staging = self.__deferred
                return True
            else:
                print(colorama.Fore.GREEN + self.__app.name + ": Previously downloaded update is not latest version, removing")
                shutil.rmtree(self.__deferred)
        # Create folder structure if it doesn't exist
        os.makedirs(self.__staging, exist_ok=True)
        # Make sure staging directory is empty
        shutil.rmtree(self.__staging)
        os.mkdir(self.__staging)
        release_latest = self.__app.version_latest["blobs"]
        if len(release_latest) == 0:
            print("No matching downloads for the latest version")
        for url in release_latest:
            filename = self.__url_downloader(url)
            archives = "001|7z|bz2|bzip2|gz|gzip|lzma|rar|tar|tgz|txz|xz|zip"
            if "installer" in self.__app.optionals and self.__app.optionals["installer"] == "sfx":
                archives = f"exe|{archives}"
            if filename and re.fullmatch(f"^.*\\.({archives})$", filename.casefold()):
                subprocess.run(f'{SEVENZIP} x -aoa "{filename}"', cwd=self.__staging, stdout=subprocess.DEVNULL)
                os.remove(os.path.join(self.__staging, filename))
                # Handle zipped installer case
                extracted = os.listdir(self.__staging)
                if len(extracted) == 1:
                    filename = extracted[0]
            if filename and re.fullmatch("^.*\\.exe$", filename.casefold()):
                if "installer" in self.__app.optionals and self.__app.optionals["installer"] == "innoextract":
                    subprocess.run(f'{INNOEXTRACT} -n "{filename}"', cwd=self.__staging, stdout=subprocess.DEVNULL)
                    os.remove(os.path.join(self.__staging, filename))
                elif "installer" not in self.__app.optionals:
                    os.rename(os.path.join(self.__staging, filename),
                              os.path.join(self.__staging, f"{self.__app.name}.exe"))
        return False

    def __url_downloader(self, url):
        """
        curl without curl

        :param url:
        :return:
        """
        url = self.__normalize_url(url, source=self.__app.url)
        print(f"Downloading file from: {url}")
        headers = {'User-Agent': 'Superelixier Updater (Contact: @FroyoXSG on GitHub)'}
        response = requests.get(url, allow_redirects=True, headers=headers, stream=True)
        tmpfile = os.path.join(self.__staging, "download-incomplete")
        if response.headers.get('refresh'):
            old_url = url
            url = response.headers["refresh"].split(';')[-1]
            if "url=" in url.lower():
                url = url.split("=")[-1]
                url = self.__normalize_url(url, source=old_url)
            print(f"Redirected to: {url}")
            response = requests.get(url, allow_redirects=True, headers=headers, stream=True)
        elif response.headers["content-type"]:
            ct = response.headers["content-type"]
            if "text/html" in ct.lower():
                old_url = url
                javascript_download = "{window.location *= *('|\")(.*)('|\");*\\}"
                with open(tmpfile, "wb") as fd:
                    for chunk in response.iter_content(chunk_size=1024):
                        fd.write(chunk)
                with open(tmpfile, 'r') as file:
                    html = file.read()
                match = re.search(javascript_download, html)
                if match:
                    url = self.__normalize_url(match.group(2), source=old_url)
                    print(f"Redirected to: {url}")
                else:
                    raise ValueError(f"{self.__app.name}: Failed to find URL")
                if self.__check_domain(old_url, url):
                    response = requests.get(url, allow_redirects=True, headers=headers, stream=True)
                else:
                    raise ValueError(f"{self.__app.name}: Could not do a JavaScript-triggered download because the download domain didn't match a trusted domain we know.")
        with open(tmpfile, "wb") as fd:
            for chunk in response.iter_content(chunk_size=1024):
                fd.write(chunk)
        filename = os.path.join(self.__staging, self.__get_remote_filename(url, response))
        os.rename(tmpfile, filename)
        return filename

    def __normalize_url(self, url, source=None):
        skeleton = [None, None, None, None, None, None]
        try:
            url_parsed = urlparse(html.unescape(url), scheme="https")
            if source:
                source_parsed = urlparse(html.unescape(source), scheme="https")
            else:
                source_parsed = skeleton
            for i in range(6):
                skeleton[i] = url_parsed[i]
                if i < 2 and skeleton[i] == '':
                    skeleton[i] = source_parsed[i]
            if None in skeleton[0:5]:
                raise ValueError
            url = urlunparse(skeleton)
        except BaseException:
            raise ValueError(f"{self.__app.name}: Failed to build URL")
        return url

    def __project_normalize(self):
        normalize_failure = False
        normalize_done = False
        while not normalize_done:
            extracted = os.listdir(self.__staging)
            if len(extracted) == 0:
                print("Failure downloading or extracting this app")
                normalize_done = True
                normalize_failure = True
            elif len(extracted) == 1:
                extracted_dir = os.path.join(self.__staging, extracted[0])
                if os.path.isdir(extracted_dir):
                    for file in os.listdir(extracted_dir):
                        shutil.move(
                            os.path.join(extracted_dir, file),
                            os.path.join(self.__staging, file)
                        )
                    os.rmdir(extracted_dir)
                elif os.path.isfile:
                    normalize_done = True
            elif len(extracted) > 1:
                print(colorama.Style.BRIGHT + f"{self.__app.name}: extracted files")
                strs = []
                for extracted in extracted:
                    print_string = extracted
                    for pattern in self.__app.blob_unwanted:
                        if re.fullmatch(pattern, extracted):
                            print_string = colorama.Fore.RED + extracted + " (removed)" + colorama.Fore.RESET
                            full_path = os.path.join(self.__staging, extracted)
                            if os.path.isfile(full_path):
                                os.remove(full_path)
                            if os.path.isdir(full_path):
                                shutil.rmtree(full_path)
                    strs.append(print_string)
                print(", ".join(strs))
                normalize_done = True
        if not normalize_failure:
            with open(os.path.join(self.__staging, "superelixier.json"), "w") as file:
                json.dump(self.__app.version_latest, file)

    def __project_merge_oldnew(self):
        # Data to keep
        keep_list = self.__list_appdatas(self.__app)
        # Full dir tree list
        full_list = self.__list_folder(self.__staging)
        # Lock all files
        opened_files = self.__lock_folder(self.__app, self.__staging, full_list)
        if opened_files is None:
            return False
        # Remove appdatas from staging
        for file in keep_list:
            file_to_protect = file.replace(self.__app.appdir, self.__staging)
            if file_to_protect in full_list:
                try:
                    os.remove(file_to_protect)
                    full_list.remove(file_to_protect)
                except PermissionError:
                    raise PermissionError(f"Error updating {self.__app.name}: Permission denied for {file_to_protect}")
        # Create history folder
        if self.__keep_history:
            os.makedirs(self.__history, exist_ok=True)
        # Move to new location
        for update_file in full_list:
            stage_location = update_file
            new_location = update_file.replace(self.__staging, self.__app.appdir)
            os.makedirs(os.path.split(new_location)[0], exist_ok=True)
            if os.path.exists(new_location):
                if self.__keep_history:
                    history_location = new_location.replace(self.__app.appdir, self.__history)
                    os.makedirs(os.path.split(history_location)[0], exist_ok=True)
                    # close file
                    if new_location in opened_files:
                        opened_files[new_location].close()
                    os.rename(new_location, history_location)
                    os.rename(stage_location, new_location)
                else:
                    os.replace(stage_location, new_location)
            else:
                os.rename(stage_location, new_location)
        for key in opened_files:
            opened_files[key].close()
        self.__remove_empty_dirs(self.__staging)
        # Ideally don't create these folders in the first place:
        self.__remove_empty_dirs(os.path.split(self.__history)[0], delete_top=True)
        return True

    def __defer_update(self):
        """
        If the new files couldn't be moved over (opened files in target), prepare update files for re-use next run.
        If the current job was already a deferred job, do nothing.

        :return:
        """
        if self.__staging != self.__deferred:
            # Clear out possible orphaned files
            if os.path.isdir(self.__deferred):
                shutil.rmtree(self.__deferred)
            os.makedirs(os.path.split(self.__deferred)[0], exist_ok=True)
            os.rename(self.__staging, self.__deferred)

    def __post_install(self):
        """
        Actions to run after the boilerplate installation process.

        :return:
        """
        if self.__app.name in ["VSCode", "VSCodium"]:
            os.makedirs(os.path.join(self.__app.appdir, "data"), exist_ok=True)

    @staticmethod
    def __list_folder(folder):
        """

        :param folder: Folder to scan
        :return: List of absolute file paths
        """
        full_list = []
        for root, _, files in os.walk(folder):
            for file in files:
                my_path = os.path.join(root, file)
                if os.path.isfile(my_path):
                    full_list.append(my_path)
        return full_list

    @staticmethod
    def __list_appdatas(app: GenericApp):
        keep_list = []
        missing_appdata = []
        for appdata in app.appdatas:
            data = os.path.join(app.appdir, *appdata.split("/"))
            if os.path.exists(data):
                if os.path.isfile(data):
                    keep_list.append(data)
                if os.path.isdir(data):
                    for root, _, files in os.walk(data):
                        for file in files:
                            my_file = os.path.join(root, file)
                            keep_list.append(my_file)
            else:
                missing_appdata.append(appdata)
        if len(missing_appdata) != 0:
            print(colorama.Fore.MAGENTA + f"Old appdatas not found: {', '.join(missing_appdata)}")
        return keep_list

    @staticmethod
    def __lock_folder(app, staging, staging_list):
        """
        Open all files in binary append mode to get exclusive access. Close all files if any file is in use.
        :param app:
        :return: Dictionary with the file handles. Invoker must close these again.
        """
        opened_files = {}
        target_list = []
        for my_file in staging_list:
            target_list.append(my_file.replace(staging, app.appdir))
        # Here we could also check if any binaries are running and not even bother with trying to lock all files.
        file_list = FileHandler.__list_folder(app.appdir)
        for my_file in file_list:
            if my_file not in target_list:
                file_list.remove(my_file)
        try:
            for existing_file in file_list:
                # There is a limit of 2048 opened files per process.
                if len(file_list) <= 2000:
                    if os.path.isfile(existing_file):
                        opened_files[existing_file] = open(existing_file, 'ab')
                else:
                    if os.path.isfile(existing_file) and re.search("\\.(bat|cmd|com|dll|exe|elf|js|jse|msc|ps1|sh|vbe|vbs|wsf|wsh)$", os.path.split(existing_file)[-1].casefold()):
                        opened_files[existing_file] = open(existing_file, 'ab')
        except PermissionError:
            print(colorama.Fore.MAGENTA + colorama.Style.BRIGHT + app.name + f": Folder is in use. Update files will be moved next time.")
            for key in opened_files:
                opened_files[key].close()
            return None
        except OSError:
            print(colorama.Fore.MAGENTA + colorama.Style.BRIGHT + app.name + f": Couldn't get folder lock.")
            for key in opened_files:
                opened_files[key].close()
            return None
        return opened_files

    @staticmethod
    def __remove_empty_dirs(top_dir, delete_top=False):
        """
        Delete empty folders created by this program. Do not use on app folders! We don't mess with the UX of installed apps that way.
        :param top_dir:
        :param delete_top:
        :return:
        """
        empty_dirs = True
        while empty_dirs:
            empty_dirs = False
            for root, subdirs, _ in os.walk(top_dir):
                for subdir in subdirs:
                    my_path = os.path.join(root, subdir)
                    if len(os.listdir(os.path.join(root, subdir))) == 0:
                        empty_dirs = True
                        os.rmdir(my_path)
        if delete_top:
            try:
                if len(os.listdir(top_dir)) == 0:
                    os.rmdir(top_dir)
            except FileNotFoundError:
                pass

    @staticmethod
    def __get_remote_filename(url, response):
        cd = response.headers.get('content-disposition')
        if cd:
            filename = re.findall('filename=(.+)', cd)[0]
        else:
            filename = url.split("/")[-1]
            if re.search("^.*?\\.(exe|001|7z|bz2|bzip2|gz|gzip|lzma|rar|tar|tgz|txz|xz|zip)\\?", filename):
                filename = filename.split("?")[0]
        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
        filename = ''.join(c for c in filename if c in valid_chars)
        return filename

    @staticmethod
    def make_path_native(path):
        crumbs = path.split("/")
        if ":" in crumbs[0] and ":\\" not in crumbs[0]:
            crumbs[0] = crumbs[0].replace(":", ":\\")
        return os.path.join(*crumbs)

    @staticmethod
    def pre_exit_cleanup(configuration_local: dict):
        """
        Remove cache directories created by this program.

        :param configuration_local:
        :return:
        """
        for target in configuration_local:
            cache = os.path.join(FileHandler.make_path_native(target), ".superelixier-cache")
            FileHandler.__remove_empty_dirs(cache, delete_top=True)

    def project_update(self):
        reused_files = self.__project_download()
        if not reused_files:
            self.__project_normalize()
        if not self.__project_merge_oldnew():
            self.__defer_update()
        self.__post_install()

    def project_install(self):
        reused_files = self.__project_download()
        if not reused_files:
            self.__project_normalize()
        if os.listdir(self.__staging):
            os.rename(self.__staging, self.__app.appdir)
        self.__post_install()

    @staticmethod
    def __check_domain(old_url, new_url):
        # I considered slicing to second-level domain and TLD here. But since the list of [PSDs](https://publicsuffix.org/) is ever-expanding...
        # This will have to do until I have a safe method to handle PSDs.
        if urlparse(old_url).netloc == urlparse(new_url).netloc:
            return True
        else:
            return False
