"""
CTSM-specific test that first performs a GDD-generating run, then calls
Python code to generate the maturity requirement file. This is then used
in a sowing+maturity forced run, which finally is tested to ensure
correct behavior.

Currently only supports 10x15 and f19_g17 resolutions. Eventually, I want
this test to be able to generate its own files at whatever resolution it's
called at. Well, really, the ultimate goal would be to give CLM the files
at the original resolution (for GGCMI phase 3, 0.5°) and have the stream
code do the interpolation. However, that wouldn't act on harvest dates
(which are needed for generate_gdds.py). I could have Python interpolate
those, but this would cause a potential inconsistency.
"""

import os
import re
import subprocess
from CIME.SystemTests.system_tests_common import SystemTestsCommon
from CIME.XML.standard_module_setup import *
from CIME.SystemTests.test_utils.user_nl_utils import append_to_user_nl_files
import shutil, glob

logger = logging.getLogger(__name__)

# SSR: This was originally ctsm_pylib, but the fact that it's missing
#      cf_units caused problems in utils.import_ds().
this_conda_env = "ctsm_pylib"

class RXCROPMATURITY(SystemTestsCommon):

    def __init__(self, case):
        # initialize an object interface to the SMS system test
        SystemTestsCommon.__init__(self, case)
        
        # Ensure run length is at least 5 years. Minimum to produce one complete growing season (i.e., two complete calendar years) actually 4 years, but that only gets you 1 season usable for GDD generation, so you can't check for season-to-season consistency.
        stop_n = self._case.get_value("STOP_N")
        stop_option = self._case.get_value("STOP_OPTION")
        stop_n_orig = stop_n
        stop_option_orig = stop_option
        if "nsecond" in stop_option:
            stop_n /= 60
            stop_option = "nminutes"
        if "nminute" in stop_option:
            stop_n /= 60
            stop_option = "nhours"
        if "nhour" in stop_option:
            stop_n /= 24
            stop_option = "ndays"
        if "nday" in stop_option:
            stop_n /= 365
            stop_option = "nyears"
        if "nmonth" in stop_option:
            stop_n /= 12
            stop_option = "nyears"
        error_message = None
        if "nyear" not in stop_option:
            error_message = (
                f"STOP_OPTION ({stop_option_orig}) must be nsecond(s), nminute(s), "
                + "nhour(s), nday(s), nmonth(s), or nyear(s)"
            )
        if stop_n < 5:
            error_message = (
                "RXCROPMATURITY must be run for at least 5 years; you requested "
                + f"{stop_n_orig} {stop_option_orig[1:]}"
            )
        if error_message is not None:
            logger.error(error_message)
            raise RuntimeError(error_message)

        # Get the number of complete years that will be run
        self._run_Nyears = int(stop_n)

    def run_phase(self):
        # Modeling this after the SSP test, we create a clone to be the case whose outputs we don't
        # want to be saved as baseline.

        #-------------------------------------------------------------------
        # (1) Set up GDD-generating run
        #-------------------------------------------------------------------
        # Create clone to be GDD-Generating case
        logger.info("SSRLOG  cloning setup")
        case_rxboth = self._case
        caseroot = self._case.get_value("CASEROOT")
        clone_path = f"{caseroot}.gddgen"
        self._path_gddgen = clone_path
        if os.path.exists(self._path_gddgen):
            shutil.rmtree(self._path_gddgen)
        logger.info("SSRLOG  cloning")
        case_gddgen = self._case.create_clone(clone_path, keepexe=True)
        logger.info("SSRLOG  done cloning")

        os.chdir(self._path_gddgen)
        self._set_active_case(case_gddgen)

        # Set up stuff that applies to both tests
        self._setup_all()

        # Add stuff specific to GDD-Generating run
        logger.info("SSRLOG  modify user_nl files: generate GDDs")
        self._append_to_user_nl_clm([
            "generate_crop_gdds = .true.",
            "use_mxmat = .false.",
        ])
        
        """
        If needed, generate a surface dataset file with no crops missing years
        """
        
        # Is flanduse_timeseries defined? If so, where is it?
        case_gddgen.create_namelists(component='lnd')
        self._lnd_in_path = os.path.join(self._path_gddgen, 'CaseDocs', 'lnd_in')
        self._flanduse_timeseries_in = None
        with open (self._lnd_in_path,'r') as lnd_in:
            for line in lnd_in:
                flanduse_timeseries_in = re.match(r" *flanduse_timeseries *= *'(.*)'", line)
                if flanduse_timeseries_in:
                    self._flanduse_timeseries_in = flanduse_timeseries_in.group(1)
                    break
        
        # If flanduse_timeseries is defined, we need to make our own version for
        # this test (if we haven't already).
        if self._flanduse_timeseries_in is not None:
            
            # Download files from the server, if needed
            case_gddgen.check_all_input_data()
            
            # Make custom version of flanduse_timeseries
            logger.info("SSRLOG  run make_lu_for_gddgen")
            self._run_make_lu_for_gddgen(case_gddgen)
        
        #-------------------------------------------------------------------
        # (2) Perform GDD-generating run and generate prescribed GDDs file
        #-------------------------------------------------------------------
        logger.info("SSRLOG  Start GDD-Generating run")
        
        # As per SSP test:
        # "No history files expected, set suffix=None to avoid compare error"
        # We *do* expect history files here, but anyway. This works.
        self._skip_pnl = False
        self.run_indv(suffix=None, st_archive=True)
        
        self._run_generate_gdds(case_gddgen)
        
        #-------------------------------------------------------------------
        # (3) Set up and perform Prescribed Calendars run
        #-------------------------------------------------------------------
        os.chdir(caseroot)
        self._set_active_case(case_rxboth)

        # Set up stuff that applies to both tests
        self._setup_all()

        # Add stuff specific to Prescribed Calendars run
        logger.info("SSRLOG  modify user_nl files: Prescribed Calendars")
        self._append_to_user_nl_clm([
            "generate_crop_gdds = .false.",
            f"stream_fldFileName_cultivar_gdds = '{self._gdds_file}'",
        ])
        
        self.run_indv()
        
        #-------------------------------------------------------------------
        # (4) Check Prescribed Calendars run
        #-------------------------------------------------------------------
        logger.info("SSRLOG  output check: Prescribed Calendars")
        self._run_check_rxboth_run()


    def _setup_all(self):
        logger.info("SSRLOG  _setup_all start")

        """
        Get some info
        """
        self._ctsm_root = self._case.get_value('COMP_ROOT_DIR_LND')
        run_startdate = self._case.get_value('RUN_STARTDATE')
        self._run_startyear = int(run_startdate.split('-')[0])
        
        """
        Get and set sowing and harvest dates
        """
        
        # Get sowing and harvest dates for this resolution.
        # Eventually, I want to remove these hard-coded resolutions so that this test can generate
        # its own sowing and harvest date files at whatever resolution is requested.
        lnd_grid = self._case.get_value("LND_GRID")
        blessed_crop_dates_dir="/glade/work/samrabin/crop_dates_blessed"
        if lnd_grid == "10x15":
            self._sdatefile = os.path.join(
                blessed_crop_dates_dir,
                "sdates_ggcmi_crop_calendar_phase3_v1.01_nninterp-f10_f10_mg37.2000-2000.20230330_165301.fill1.nc")
            self._hdatefile = os.path.join(
                blessed_crop_dates_dir,
                "hdates_ggcmi_crop_calendar_phase3_v1.01_nninterp-f10_f10_mg37.2000-2000.20230330_165301.fill1.nc")
        elif lnd_grid == "1.9x2.5":
            self._sdatefile = os.path.join(
                blessed_crop_dates_dir,
                "sdates_ggcmi_crop_calendar_phase3_v1.01_nninterp-f19_g17.2000-2000.20230102_175625.fill1.nc")
            self._hdatefile = os.path.join(
                blessed_crop_dates_dir,
                "hdates_ggcmi_crop_calendar_phase3_v1.01_nninterp-f19_g17.2000-2000.20230102_175625.fill1.nc")
        else:
            print("ERROR: RXCROPMATURITY currently only supports 10x15 and 1.9x2.5 resolutions")
            raise
        if not os.path.exists(self._sdatefile):
            print(f"ERROR: Sowing date file not found: {self._sdatefile}")
            raise
        if not os.path.exists(self._hdatefile):
            print(f"ERROR: Harvest date file not found: {self._sdatefile}")
            raise
        
        # Set sowing dates file (and other crop calendar settings) for all runs
        logger.info("SSRLOG  modify user_nl files: all tests")
        self._modify_user_nl_allruns()
        logger.info("SSRLOG  _setup_all done")

         
    def _run_make_lu_for_gddgen(self, case_gddgen):
        
        # Where we will save the flanduse_timeseries version for this test
        self._flanduse_timeseries_out = os.path.join(self._path_gddgen, 'flanduse_timeseries.nc')
        
        # Make flanduse_timeseries for this test, if not already done
        if not os.path.exists(self._flanduse_timeseries_out):
            
            first_fake_year = self._run_startyear
            last_fake_year = first_fake_year + self._run_Nyears
            
            tool_path = os.path.join(self._ctsm_root,
                                    'python', 'ctsm', 'crop_calendars',
                                    'make_lu_for_gddgen.py')
            command = " ".join([
                    f"python3 {tool_path}",
                    f"--flanduse-timeseries {self._flanduse_timeseries_in}",
                    f"-y1 {first_fake_year}",
                    f"-yN {last_fake_year}",
                    f"--outfile {self._flanduse_timeseries_out}",
                    ])
            self._run_python_script(case_gddgen, command, tool_path)
        
        # Modify namelist
        logger.info("SSRLOG  modify user_nl files: new flanduse_timeseries")
        self._append_to_user_nl_clm([
            "flanduse_timeseries = '{}'".format(self._flanduse_timeseries_out),
        ])


    # Unused because I couldn't get the GDD-Generating run to work with the fsurdat file generated
    # by make_surface_for_gddgen.py. However, I think it'd be cleaner to just do the GDD-Generating
    # run with a surface file (and no flanduse_timeseries file) since that run relies on land use
    # staying constant. So it'd be nice to get this working eventually.
    def _run_make_surface_for_gddgen(self, case_gddgen):
        
        # fsurdat should be defined. Where is it?
        self._fsurdat_in = None
        with open (self._lnd_in_path,'r') as lnd_in:
            for line in lnd_in:
                fsurdat_in = re.match(r" *fsurdat *= *'(.*)'", line)
                if fsurdat_in:
                    self._fsurdat_in = fsurdat_in.group(1)
                    break
        if self._fsurdat_in is None:
            print("fsurdat not defined")
            raise
        
        # Where we will save the fsurdat version for this test
        self._fsurdat_out = os.path.join(self._path_gddgen, 'fsurdat.nc')
        
        # Make fsurdat for this test, if not already done
        if not os.path.exists(self._fsurdat_out):
            tool_path = os.path.join(self._ctsm_root,
                                    'python', 'ctsm', 'crop_calendars',
                                    'make_surface_for_gddgen.py')
            command = f"python3 {tool_path} "\
                    + f"--flanduse-timeseries {self._flanduse_timeseries_in} "\
                    + f"--fsurdat {self._fsurdat_in} "\
                    + f"--outfile {self._fsurdat_out}"
            self._run_python_script(case_gddgen, command, tool_path)
        
        # Modify namelist
        logger.info("SSRLOG  modify user_nl files: new fsurdat")
        self._append_to_user_nl_clm([
            "fsurdat = '{}'".format(self._fsurdat_out),
            "do_transient_crops = .false.",
            "flanduse_timeseries = ''",
            "use_init_interp = .true.",
        ])
        
    
    def _run_check_rxboth_run(self):
        
        output_dir = os.path.join(self._get_caseroot(), "run")
        first_usable_year = self._run_startyear + 2
        last_usable_year = self._run_startyear + self._run_Nyears - 2
                
        tool_path = os.path.join(self._ctsm_root,
                                'python', 'ctsm', 'crop_calendars',
                                'check_rxboth_run.py')
        command = f"python3 {tool_path} "\
                + f"--directory {output_dir} "\
                + f"-y1 {first_usable_year} "\
                + f"-yN {last_usable_year} "\
                + f"--rx-sdates-file {self._sdatefile} "\
                + f"--rx-gdds-file {self._gdds_file} "
        self._run_python_script(self._case, command, tool_path)                
    
    
    def _modify_user_nl_allruns(self):
        nl_additions = [
            "stream_meshfile_cropcal = '{}'".format(self._case.get_value("LND_DOMAIN_MESH")),
            "stream_fldFileName_sdate = '{}'".format(self._sdatefile),
            "stream_year_first_cropcal = 2000",
            "stream_year_last_cropcal = 2000",
            "model_year_align_cropcal = 2000",
            " ",
            "! (h1) Daily outputs for GDD generation and figure-making",
            "hist_fincl2 = 'HUI', 'GDDACCUM', 'GDDHARV'",
            "hist_nhtfrq(2) = -24",
            "hist_mfilt(2) = 365",
            "hist_type1d_pertape(2) = 'PFTS'",
            "hist_dov2xy(2) = .false.",
            " ",
            "! (h2) Annual outputs for GDD generation (checks)",
            "hist_fincl3 = 'GRAINC_TO_FOOD_PERHARV', 'GRAINC_TO_FOOD_ANN', 'SDATES', 'SDATES_PERHARV', 'SYEARS_PERHARV', 'HDATES', 'GDDHARV_PERHARV', 'GDDACCUM_PERHARV', 'HUI_PERHARV', 'SOWING_REASON_PERHARV', 'HARVEST_REASON_PERHARV'",
            "hist_nhtfrq(3) = 17520",
            "hist_mfilt(3) = 999",
            "hist_type1d_pertape(3) = 'PFTS'",
            "hist_dov2xy(3) = .false.",
        ]
        self._append_to_user_nl_clm(nl_additions)


    def _run_generate_gdds(self, case_gddgen):
        self._generate_gdds_dir = os.path.join(self._path_gddgen, "generate_gdds_out")
        os.makedirs(self._generate_gdds_dir)

        # Get arguments to generate_gdds.py
        dout_sr = case_gddgen.get_value("DOUT_S_ROOT")
        input_dir = os.path.join(dout_sr, "lnd", "hist")
        first_season = self._run_startyear + 2
        last_season = self._run_startyear + self._run_Nyears - 2
        sdates_file = self._sdatefile
        hdates_file = self._hdatefile

        # It'd be much nicer to call generate_gdds.main(), but I can't import generate_gdds.
        tool_path = os.path.join(self._ctsm_root,
                                 'python', 'ctsm', 'crop_calendars',
                                 'generate_gdds.py')
        command = " ".join([
                f"python3 {tool_path}",
                f"--input-dir {input_dir}",
                f"--first-season {first_season}",
                f"--last-season {last_season}",
                f"--sdates-file {sdates_file}",
                f"--hdates-file {hdates_file}",
                f"--output-dir generate_gdds_out"])
        self._run_python_script(case_gddgen, command, tool_path)
        
        # Where were the prescribed maturity requirements saved?
        generated_gdd_files = glob.glob(os.path.join(self._generate_gdds_dir, "gdds_*.nc"))
        generated_gdd_files = [x for x in generated_gdd_files if "fill0" not in x]
        if len(generated_gdd_files) != 1:
            print(f"ERROR: Expected one matching prescribed maturity requirements file; found {len(generated_gdd_files)}: {generated_gdd_files}")
            raise
        self._gdds_file = generated_gdd_files[0]
        

    def _get_conda_env(self):
        #
        # Add specific commands needed on different machines to get conda available
        # Use semicolon here since it's OK to fail
        #
        # Execute the module unload/load when "which conda" fails
        # eg on cheyenne
        try:
            subprocess.run( "which conda", shell=True, check=True)
            conda_env = " "
        except subprocess.CalledProcessError:
            # Remove python and add conda to environment for cheyennne
            conda_env = "module unload python; module load conda;"

        ## Run in the correct python environment
        conda_env += f" conda run -n {this_conda_env} "
        
        return( conda_env )
    
    
    def _append_to_user_nl_clm(self, additions):
        if not isinstance(additions, list):
            additions = [additions]
        caseroot = self._get_caseroot()
        for a in additions:
            append_to_user_nl_files(caseroot = caseroot,
                                    component = "clm",
                                    contents = a)
    
    
    def _run_python_script(self, case, command, tool_path):
        tool_name = os.path.split(tool_path)[-1]
        case.load_env(reset=True)
        
        # Prepend the commands to get the conda environment for python first
        conda_env = ". "+self._get_caseroot()+"/.env_mach_specific.sh; "
        conda_env += self._get_conda_env()
        command = conda_env + command
        print(f"command: {command}")
        
        # Run
        try:
            with open(tool_name + ".log", "w") as f:
                subprocess.run(command, shell=True, check=True, text=True,
                    stdout=f, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            print("ERROR while getting the conda environment and/or ")
            print(f"running the {tool_name} tool: ")
            print(f"(1) If your {this_conda_env} environment is out of date or you ")
            print(f"have not created the {this_conda_env} environment, yet, you may ")
            print("get past this error by running ./py_env_create ")
            print("in your ctsm directory and trying this test again. ")
            print("(2) If conda is not available, install and load conda, ")
            print("run ./py_env_create, and then try this test again. ")
            print("(3) If (1) and (2) are not the issue, then you may be ")
            print(f"getting an error within {tool_name} itself. ")
            print("Default error message: ")
            print(error.output)
            raise
        except:
            print(f"ERROR trying to run {tool_name}.")
            raise
