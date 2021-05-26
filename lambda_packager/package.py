import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import toml

from lambda_packager.config import Config
from lambda_packager.poetry import poetry_is_used, export_poetry


class LambdaAutoPackage:
    def __init__(self, config=None, project_directory=None, logger=None):
        if project_directory:
            self.project_directory = Path(project_directory)
        else:
            self.project_directory = Path()

        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
            self.logger.debug("set up self logging")

        if config:
            self.config = config
        else:
            self.config = LambdaAutoPackage._get_config(
                self.project_directory.joinpath("pyproject.toml")
            )

        self.tmp_folder = self._create_tmp_directory()

    def execute(self):

        if self.project_directory.joinpath("requirements.txt").is_file():
            self.logger.info("using requirements.txt file in project directory")
            requirements_file_path = self.project_directory.joinpath("requirements.txt")
            self._install_requirements_txt(
                str(self.tmp_folder), requirements_file_path=requirements_file_path
            )
        elif poetry_is_used(self.project_directory):
            self.logger.info("using pyproject.toml file in project directory")
            requirements_file_path = self.tmp_folder.joinpath("requirements.txt")
            export_poetry(
                target_path=requirements_file_path,
                project_directory=self.project_directory,
            )
            self._install_requirements_txt(
                str(self.tmp_folder),
                requirements_file_path=requirements_file_path,
                no_deps=True,
            )
        else:
            self.logger.warning("No dependency found, none will be packaged")

        self._copy_source_files(
            source_dir=self.project_directory,
            target_dir=self.tmp_folder,
        )

        self._create_zip_file(
            self.tmp_folder, str(self.project_directory.joinpath("dist/lambda.zip"))
        )

    @staticmethod
    def _create_tmp_directory():
        dirpath = tempfile.mkdtemp()
        test_path = Path(dirpath)
        assert test_path.exists()
        assert test_path.is_dir()
        return test_path

    def _copy_source_files(self, source_dir: Path, target_dir: Path):
        matching_objects = LambdaAutoPackage._get_matching_files_and_folders(
            self.config.src_patterns, source_dir
        )

        self.logger.info(f"copying {len(matching_objects)} matching_objects")
        self.logger.debug(f"copying {matching_objects} matching_objects")

        copied_locations = []
        for object in matching_objects:
            relative_path = object.relative_to(source_dir)
            new_location = target_dir.joinpath(relative_path)

            if object.is_file():
                self.logger.debug(
                    f"about to copy file from {object} --> {new_location}"
                )
                new_location.parent.mkdir(exist_ok=True)

                if (
                    self.config.ignore_hidden_files
                    and LambdaAutoPackage._is_hidden_file(str(relative_path))
                ):
                    self.logger.warning(f"skipping file {object.resolve()}")
                else:
                    copied_locations.append(str(shutil.copyfile(object, new_location)))

            elif object.is_dir():
                self.logger.debug(
                    f"about to copy directory from {object} --> {new_location}"
                )

                ignore_files_callback = None
                if self.config.ignore_hidden_files:
                    ignore_files_callback = self._is_hidden_file_list

                copied_locations.append(
                    str(
                        shutil.copytree(
                            str(object),
                            str(new_location),
                            dirs_exist_ok=True,
                            ignore=ignore_files_callback,
                        )
                    )
                )
            else:
                self.logger.warning(
                    f"the path '{object}' was nether a file or directory"
                )

        copied_locations_string = "\n".join(copied_locations)
        self.logger.info(f"copied the following locations: \n{copied_locations_string}")

    def _is_hidden_file_list(self, src, files):
        if LambdaAutoPackage._is_hidden_file(src):
            self.logger.warning(f"skipping hidden folder {Path(src).resolve()}")
            return files
        files_to_skip = list(filter(LambdaAutoPackage._is_hidden_file, files))
        if files_to_skip:
            self.logger.warning(
                f"skipping hidden files {list(map(lambda file: Path(file).resolve(), files_to_skip))}"
            )
        return files_to_skip

    @staticmethod
    def _is_hidden_file(name):
        return name.startswith(".") or "/." in name

    @staticmethod
    def _get_matching_files_and_folders(pattern_list, source_dir):
        matching_objects = set()
        for pattern in pattern_list:
            matching_objects.update(source_dir.rglob(pattern))

        return matching_objects

    @staticmethod
    def _install_requirements_txt(target, requirements_file_path: Path, no_deps=False):
        # https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program
        if not requirements_file_path.is_file():
            raise ValueError(
                f"could not find requirements.txt file at '{requirements_file_path}'"
            )

        logging.info(f"installing pip requirements to '{target}'")
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            requirements_file_path,
            "--target",
            target,
        ]
        if no_deps:
            cmd.append("--no-deps")

        return subprocess.check_output(cmd)

    @staticmethod
    def _create_zip_file(source_dir, target):
        if target.endswith(".zip"):
            Path(target).parent.mkdir(exist_ok=True)
            name = target[: -len(".zip")]
            shutil.make_archive(base_name=name, format="zip", root_dir=source_dir)
        else:
            raise ValueError(
                f"given target path '{target}' does not end with correct extension. should end with '.zip'"
            )

    @staticmethod
    def _read_config(file: Path):
        config = toml.loads(file.read_text())

        try:
            return config["tool"]["lambda_packager"]
        except KeyError:
            logging.warning("no config found!")
            return {}

    @staticmethod
    def _get_config(file: Path):
        if not file.is_file():
            logging.warning("no config file found!")
            return Config()

        config_dict = LambdaAutoPackage._read_config(file)
        return Config(**config_dict)
