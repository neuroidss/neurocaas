import os
import json
import traceback
import re


try:
    #import utils_param.config as config
    import utilsparam.s3
    import utilsparam.ssm
    import utilsparam.ec2
    import utilsparam.events
except Exception as e:
    error = str(e)
    stacktrace = json.dumps(traceback.format_exc())
    message = "Exception: " + error + "  Stacktrace: " + stacktrace
    err = {"message": message}
    print(err)


def respond(err, res=None):
    return {
        "statusCode": "400" if err else "200",
        "body": err["message"] if err else json.dumps(res),
        "headers": {"Content-Type": "application/json"},
    }

## Lambda code for developmemt. 
class Submission_Launch_log_demo():
    """
    Specific lambda for purposes of development.  
    """
    def __init__(self,bucket_name,key,time):
        ## Initialize as before:
        # Get Upload Location Information
        self.bucket_name = bucket_name
        ## Get directory above the input directory. 
        self.path = re.findall('.+?(?=/'+os.environ["INDIR"]+')',key)[0] 
        ## Now add in the time parameter: 
        self.time = time
        ## We will index by the submit file name prefix if it exists: 
        submit_search = re.findall('.+?(?=/submit.json)',os.path.basename(key))
        try:
            submit_name = submit_search[0]
        except IndexError as e:
            ## If the filename is just "submit.json, we just don't append anything to the job name. "
            submit_name = ""
            
        ## Now we're going to get the path to the results directory: 
        self.jobname = "job"+submit_name+'epi_demo'
        jobpath = os.path.join(self.path,os.environ['OUTDIR'],self.jobname)
        self.jobpath = jobpath
        ## Reset this directory
        create_jobdir  = utilsparam.s3.mkdir_reset(self.bucket_name, os.path.join(self.path,os.environ['OUTDIR']),self.jobname)
        
        self.logger = utilsparam.s3.JobLogger_demo(self.bucket_name, self.jobpath)
        self.logger.append("Initializing EPI analysis: Parameter search for 2D LDS.")
        self.logger.write()
        #self.out_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.OUTDIR)
        #self.in_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.INDIR)

        # Load Content Of Submit File 
        submit_file = utilsparam.s3.load_json(bucket_name, key)
        ## Check what instance we should use. 
        try:
            self.instance_type = submit_file['instance_type'] # TODO default option from config
        except KeyError as ke: 
            msg = "Using default instance type {} from config file".format(os.environ["INSTANCE_TYPE"])
            self.instance_type = os.environ["INSTANCE_TYPE"]
            ## Log this message.- not crucial for logging. 
            #self.logger.append(msg)
            #self.logger.write()

        ## These next two check that the submit file is correctly formatted
        ## Check that we have a dataname field:
        submit_errmsg = "INPUT ERROR: Submit file does not contain field {}, needed to analyze data."
        try: 
            self.data_name = submit_file['dataname'] # TODO validate extensions 
        except KeyError as ke:

            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError("Missing data name to analyze")

        try:
            self.config_name = submit_file["configname"] 
            self.logger.assign_config(self.config_name)
        except KeyError as ke:
            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError(os.environ["MISSING_CONFIG_ERROR"])

        self.logger.append("EPI analysis request detected with dataset {}, config file {}. Reading EPI blueprint.".format(self.data_name,self.config_name))
        self.logger.write()

        ## Check that we have the actual data in the bucket.  
        exists_errmsg = "INPUT ERROR: S3 Bucket does not contain {}"
        if not utilsparam.s3.exists(self.bucket_name,self.data_name): 
            msg = exists_errmsg.format(self.data_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("dataname given does not exist in bucket.")
        elif not utilsparam.s3.exists(self.bucket_name,self.config_name): 
            msg = exists_errmsg.format(self.config_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("configname given does not exist in bucket.")
        ###########################

        ## Now get the actual paths to relevant data from the foldername: 

        self.filenames = utilsparam.s3.extract_files(self.bucket_name,self.data_name,ext = None) 
        assert len(self.filenames) > 0, "we must have data to analyze."

    def acquire_instance(self):
        """ Acquires & Starts New EC2 Instances Of The Requested Type & AMI. Specialized certificate messages. """
        instances = []
        nb_instances = len(self.filenames)

        ## Check how many instances are running. 
        active = utilsparam.ec2.count_active_instances(self.instance_type)
        ## Ensure that we have enough bandwidth to support this request:
        if active +nb_instances < int(os.environ['DEPLOY_LIMIT']):
            pass
        else:
            self.logger.append("RESOURCE ERROR: Instance requests greater than pipeline bandwidth. Please contact NCAP administrator.")
        

        for i in range(nb_instances):
            instance = utilsparam.ec2.launch_new_instance(
            instance_type=self.instance_type, 
            ami=os.environ['AMI'],
            logger= []# self.logger
            )
            instances.append(instance)
        self.logger.append("Setting up {} EPI infrastructures from blueprint, please wait...".format(nb_instances))
        self.instances = instances

    def start_instance(self):
        """ Starts new instances if stopped. We write a special loop for this one because we only need a single 60 second pause for all the intances, not one for each in serial. Specialized certificate messages. """
        utilsparam.ec2.start_instances_if_stopped(
            instances=self.instances,
            logger=[]#self.logger
        )
        self.logger.append("Created {} EPI infrastructures with 4 cpus, 16 GB memory ".format(len(self.filenames)))

    def process_inputs(self):
        """ Initiates Processing On Previously Acquired EC2 Instance. This version requires that you include a config (fourth) argument """
        print(self.bucket_name,'bucket name')
        print(self.filenames,'filenames')
        print(os.environ['OUTDIR'],'outdir')
        print(os.environ['COMMAND'],'command')
        try: 
            os.environ['COMMAND'].format("a","b","c","d")
        except IndexError as ie:
            msg = "not enough arguments in the COMMAND argument."
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("Not the correct format for arguments.")
     

        ## Should we vectorize the log here? 
        outpath_full = os.path.join(os.environ['OUTDIR'],self.jobname)

        #[self.logger.append("Starting analysis with parameter set {}, dataset {}".format(
        #    f+1,
        #    filename
        #    )
        #) for f,filename in enumerate(self.filenames)]
        #[self.logger.append("Starting analysis with parameter set {}: {}".format(
        #    f+1,
        #    os.environ['COMMAND'].format(
        #        self.bucket_name, filename, outpath_full, self.config_name
        #    )
        #)) for f,filename in enumerate(self.filenames)]
        print([os.environ['COMMAND'].format(
              self.bucket_name, filename, outpath_full, self.config_name
              ) for filename in self.filenames],"command send")
        for f,filename in enumerate(self.filenames):
            response = utilsparam.ssm.execute_commands_on_linux_instances(
                commands=[os.environ['COMMAND'].format(
                    self.bucket_name, filename, outpath_full, self.config_name
                    )], # TODO: variable outdir as option
                instance_ids=[self.instances[f].instance_id],
                working_dirs=[os.environ['WORKING_DIRECTORY']],
                log_bucket_name=self.bucket_name,
                log_path=os.path.join(self.jobpath,'internal_ec2_logs')
                )
            self.logger.initialize_datasets_dev(filename,self.instances[f].instance_id,response["Command"]["CommandId"])
            self.logger.append("Starting analysis {} with parameter set {}".format(f+1,os.path.basename(filename)))
            self.logger.write()
        self.logger.append("All jobs submitted. Processing...")


    ## Declare rules to monitor the states of these instances.  
    def put_instance_monitor_rule(self): 
        """ For multiple datasets."""
        for instance in self.instances:
            self.logger.append('Setting up monitoring on instance '+str(instance))
            ## First declare a monitoring rule for this instance: 
            ruledata,rulename = utilsparam.events.put_instance_rule(instance.instance_id)
            arn = ruledata['RuleArn']
            ## Now attach it to the given target
            targetdata = utilsparam.events.put_instance_target(rulename) 

## Lambda code for deployment from other buckets. 
class Submission_Launch_log_test():
    """
    Object for ncap upload handling where inputs can come from specific user buckets. We then need to partition and replicate output between the user input bucket and the submit bucket. Input and submit buckets are structured as follows:  
    Input Bucket:
    -inputs
      +data
      +configs
    -results
      -job folder
        +results
        +per-dataset logs
        +per-job certificate

    Submit Bucket: 
    - group name
      -inputs
        +submit.json files referencing the input bucket. 
      -results
        +per-job certificate 
        +internal ec2 logs. 
    """
    def __init__(self,bucket_name,key,time):
        #### Declare basic parameters: 
        # Get Upload Location Information
        self.bucket_name = bucket_name

        ## Important paths: 
        ## Get directory above the input directory where the job was submitted. 
        self.path = re.findall('.+?(?=/'+os.environ["INDIR"]+')',key)[0] 
        ## The other important directory is the actual base directory of the input bucket itself. 

        ## Now add in the time parameter: 
        self.time = time

        #### Set up basic logging so we can get a trace when errors happen.   
        ## We will index by the submit file name prefix if it exists: 
        submit_search = re.findall('.+?(?=/submit.json)',os.path.basename(key))
        try:
            submit_name = submit_search[0]
        except IndexError as e:
            ## If the filename is just "submit.json, we just don't append anything to the job name. "
            submit_name = ""
        ## Now we're going to get the path to the results directory in the submit folder: 
        self.jobname = "job"+submit_name+self.time
        jobpath = os.path.join(self.path,os.environ['OUTDIR'],self.jobname)
        self.jobpath_submit = jobpath
        ## And create a corresponding directory in the submit area. 
        create_jobdir  = utilsparam.s3.mkdir(self.bucket_name, os.path.join(self.path,os.environ['OUTDIR']),self.jobname)
        ## a logger for the submit area.  
        self.submitlogger = utilsparam.s3.JobLogger(self.bucket_name, self.jobpath_submit)

        #### Parse submit file 
        submit_file = utilsparam.s3.load_json(bucket_name, key)
        
        ## These next three fields check that the submit file is correctly formatted
        ## Check that we have a dataname field:
        submit_errmsg = "INPUT ERROR: Submit file does not contain field {}, needed to analyze data."
        try: 
            self.input_bucket_name = submit_file["bucketname"]
            ## KEY: Now set up logging in the input folder too: 
            self.inputlogger = utilsparam.s3.JobLogger(self.input_bucket_name,os.path.join(os.environ['OUTDIR'],self.jobname)) ##TODO: this relies upon "OUTDIR" being the same in the submit and input buckets. Make sure to alter this later. 
        except KeyError as ke:

            print(submit_errmsg.format(ke))
            ## Write to logger
            self.submitlogger.append(submit_errmsg.format(ke))
            self.submitlogger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError("Missing bucket name where data is located.")

        try: 
            self.data_name = submit_file['dataname'] # TODO validate extensions 
        except KeyError as ke:

            print(submit_errmsg.format(ke))
            ## Write to logger
            self.submitlogger.append(submit_errmsg.format(ke))
            self.submitlogger.write()
            self.inputlogger.append(submit_errmsg.format(ke))
            self.inputlogger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError("Missing data name to analyze")

        try:
            self.config_name = submit_file["configname"] 
            self.submitlogger.assign_config(self.config_name)
        except KeyError as ke:
            print(submit_errmsg.format(ke))
            ## Write to logger
            self.submitlogger.append(submit_errmsg.format(ke))
            self.submitlogger.write()
            self.inputlogger.append(submit_errmsg.format(ke))
            self.inputlogger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError(os.environ["MISSING_CONFIG_ERROR"])

        ## Check that we have the actual data in the bucket.  
        exists_errmsg = "INPUT ERROR: S3 Bucket does not contain {}"
        if not utilsparam.s3.exists(self.input_bucket_name,self.data_name): 
            msg = exists_errmsg.format(self.data_name)
            self.submitlogger.append(msg)
            self.submitlogger.write()
            self.inputlogger.append(msg)
            self.inputlogger.write()
            raise ValueError("dataname given does not exist in bucket.")
        elif not utilsparam.s3.exists(self.input_bucket_name,self.config_name): 
            msg = exists_errmsg.format(self.config_name)
            self.submitlogger.append(msg)
            self.submitlogger.write()
            self.inputlogger.append(msg)
            self.inputlogger.write()
            raise ValueError("configname given does not exist in bucket.")

        ## Check what instance we should use. 
        try:
            self.instance_type = submit_file['instance_type'] 
        except KeyError as ke: 
            msg = "Instance type {} does not exist, using default from config file".format(ke)
            self.instance_type = os.environ["INSTANCE_TYPE"]
            ## Log this message.
            self.submitlogger.append(msg)
            self.submitlogger.write()
            self.inputlogger.append(msg)
            self.inputlogger.write()
        ###########################

        ## Now get the actual paths to relevant data from the foldername: 

        self.filenames = utilsparam.s3.extract_files(self.input_bucket_name,self.data_name,ext = None) 
        assert len(self.filenames) > 0, "we must have data to analyze."

    def acquire_instance(self):
        """ Acquires & Starts New EC2 Instances Of The Requested Type & AMI"""
        instances = []
        nb_instances = len(self.filenames)

        ## Check how many instances are running. 
        active = utilsparam.ec2.count_active_instances(self.instance_type)
        ## Ensure that we have enough bandwidth to support this request:
        if active +nb_instances < int(os.environ['DEPLOY_LIMIT']):
            pass
        else:
            self.submitlogger.append("RESOURCE ERROR: Instance requests greater than pipeline bandwidth. Please contact NCAP administrator.")
            self.inputlogger.append("RESOURCE ERROR: Instance requests greater than pipeline bandwidth. Please contact NCAP administrator.")
        
        for i in range(nb_instances):
            instance = utilsparam.ec2.launch_new_instance(
            instance_type=self.instance_type, 
            ami=os.environ['AMI'],
            logger=self.inputlogger
            )
            instances.append(instance)
        self.instances = instances

    def start_instance(self):
        """ Starts new instances if stopped. We write a special loop for this one because we only need a single 60 second pause for all the intances, not one for each in serial"""
        utilsparam.ec2.start_instances_if_stopped(
            instances=self.instances,
            logger=self.inputlogger
        )

    ## Declare rules to monitor the states of these instances.  
    def put_instance_monitor_rule(self): 
        """ For multiple datasets."""
        for instance in self.instances:
            self.submitlogger.append('Setting up monitoring on instance '+str(instance))
            self.inputlogger.append('Setting up monitoring on instance '+str(instance))
            ## First declare a monitoring rule for this instance: 
            ruledata,rulename = utilsparam.events.put_instance_rule(instance.instance_id)
            arn = ruledata['RuleArn']
            ## Now attach it to the given target
            targetdata = utilsparam.events.put_instance_target(rulename) 

    def process_inputs(self):
        """ Initiates Processing On Previously Acquired EC2 Instance. This version requires that you include a config (fourth) argument """
        print(self.input_bucket_name,'bucket name')
        print(self.filenames,'filenames')
        print(os.environ['OUTDIR'],'outdir')
        print(os.environ['COMMAND'],'command')
        try: 
            os.environ['COMMAND'].format("a","b","c","d")
        except IndexError as ie:
            msg = "not enough arguments in the COMMAND argument."
            self.submitlogger.append(msg)
            self.submitlogger.write()
            self.inputlogger.append(msg)
            self.inputlogger.write()
            raise ValueError("Not the correct format for arguments.")

        ## Should we vectorize the log here? 
        outpath_full = os.path.join(os.environ['OUTDIR'],self.jobname)
        [self.submitlogger.append("Sending command: {}".format(
            os.environ['COMMAND'].format(
                self.input_bucket_name, filename, outpath_full, self.config_name
            )
        )) for filename in self.filenames]
        [self.inputlogger.append("Sending command: {}".format(
            os.environ['COMMAND'].format(
                self.input_bucket_name, filename, outpath_full, self.config_name
            )
        )) for filename in self.filenames]

        print([os.environ['COMMAND'].format(
              self.input_bucket_name, filename, outpath_full, self.config_name
              ) for filename in self.filenames],"command sent")

        for f,filename in enumerate(self.filenames):
            response = utilsparam.ssm.execute_commands_on_linux_instances(
                commands=[os.environ['COMMAND'].format(
                    self.input_bucket_name, filename, outpath_full, self.config_name
                    )], # TODO: variable outdir as option
                instance_ids=[self.instances[f].instance_id],
                working_dirs=[os.environ['WORKING_DIRECTORY']],
                log_bucket_name=self.bucket_name,
                log_path=os.path.join(self.jobpath_submit,'internal_ec2_logs')
                )
            #self.submitlogger.initialize_datasets_dev(filename,self.instances[f].instance_id,response["Command"]["CommandId"])
            self.inputlogger.initialize_datasets_dev(filename,self.instances[f].instance_id,response["Command"]["CommandId"])




##########
#Legacy version kept in case things go horrifica
## Version to launch an instance
class Submission_Launch():
    """ Collection of data for a single request to process a dataset """

    def __init__(self, bucket_name, key):
        raise NotImplementedError

    def acquire_instance(self):
        raise NotImplementedError

    def start_instance(self):
        raise NotImplementedError

    def process_inputs(self):
        raise NotImplementedError
    ## Declare rules to monitor the states of these instances.  
    def put_instance_monitor_rule(self): 
        raise NotImplementedError


class Submission_Launch_folder():
    """
    Generalization of Submission_Launch to a folder. Will launch a separate instance for each file in the bucket. Can be used to replace Submission_Launch whole-hog, as giving the path to the file will still work with this implementation.     
    """
    def __init__(self, bucket_name, key):
        raise NotImplementedError
        
    def acquire_instance(self):
        """ Acquires & Starts New EC2 Instances Of The Requested Type & AMI"""
        instances = []
        nb_instances = len(self.filenames)

        ## Check how many instances are running. 
        active = utilsparam.ec2.count_active_instances(self.instance_type)
        ## Ensure that we have enough bandwidth to support this request:
        if active +nb_instances < int(os.environ['DEPLOY_LIMIT']):
            pass
        else:
            self.logger.append("RESOURCE ERROR: Instance requests greater than pipeline bandwidth. Please contact NCAP administrator.")
        

        for i in range(nb_instances):
            instance = utilsparam.ec2.launch_new_instance(
            instance_type=self.instance_type, 
            ami=os.environ['AMI'],
            logger=self.logger
            )
            instances.append(instance)
        self.instances = instances

    def start_instance(self):
        """ Starts new instances if stopped. We write a special loop for this one because we only need a single 60 second pause for all the intances, not one for each in serial"""
        utilsparam.ec2.start_instances_if_stopped(
            instances=self.instances,
            logger=self.logger
        )

    ## Declare rules to monitor the states of these instances.  
    def put_instance_monitor_rule(self): 
        """ For multiple datasets."""
        for instance in self.instances:
            self.logger.append('Setting up monitoring on instance '+str(instance))
            ## First declare a monitoring rule for this instance: 
            ruledata,rulename = utilsparam.events.put_instance_rule(instance.instance_id)
            arn = ruledata['RuleArn']
            ## Now attach it to the given target
            targetdata = utilsparam.events.put_instance_target(rulename) 

    def process_inputs(self):
        raise NotImplementedError
      

## Gets acquire, start, monitor. 
class Submission_Launch_log_dev(Submission_Launch_folder):
    """
    Latest modification (11/1) to submit framework: spawn individual log files for each dataset. . 
    """
    def __init__(self,bucket_name,key,time):
        ## Initialize as before:
        # Get Upload Location Information
        self.bucket_name = bucket_name
        ## Get directory above the input directory. 
        self.path = re.findall('.+?(?=/'+os.environ["INDIR"]+')',key)[0] 
        ## Now add in the time parameter: 
        self.time = time
        ## We will index by the submit file name prefix if it exists: 
        submit_search = re.findall('.+?(?=/submit.json)',os.path.basename(key))
        try:
            submit_name = submit_search[0]
        except IndexError as e:
            ## If the filename is just "submit.json, we just don't append anything to the job name. "
            submit_name = ""
            
        ## Now we're going to get the path to the results directory: 
        self.jobname = "job"+submit_name+self.time
        jobpath = os.path.join(self.path,os.environ['OUTDIR'],self.jobname)
        self.jobpath = jobpath
        create_jobdir  = utilsparam.s3.mkdir(self.bucket_name, os.path.join(self.path,os.environ['OUTDIR']),self.jobname)
        
        print(self.path,'path')
        self.logger = utilsparam.s3.JobLogger(self.bucket_name, self.jobpath)
        #self.out_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.OUTDIR)
        #self.in_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.INDIR)

        # Load Content Of Submit File 
        submit_file = utilsparam.s3.load_json(bucket_name, key)
        ## Check what instance we should use. 
        try:
            self.instance_type = submit_file['instance_type'] # TODO default option from config
        except KeyError as ke: 
            msg = "Instance type {} does not exist, using default from config file".format(ke)
            self.instance_type = os.environ["INSTANCE_TYPE"]
            ## Log this message.
            self.logger.append(msg)
            self.logger.write()

        ## These next two check that the submit file is correctly formatted
        ## Check that we have a dataname field:
        submit_errmsg = "INPUT ERROR: Submit file does not contain field {}, needed to analyze data."
        try: 
            self.data_name = submit_file['dataname'] # TODO validate extensions 
        except KeyError as ke:

            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError("Missing data name to analyze")

        try:
            self.config_name = submit_file["configname"] 
            self.logger.assign_config(self.config_name)
        except KeyError as ke:
            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError(os.environ["MISSING_CONFIG_ERROR"])

        ## Check that we have the actual data in the bucket.  
        exists_errmsg = "INPUT ERROR: S3 Bucket does not contain {}"
        if not utilsparam.s3.exists(self.bucket_name,self.data_name): 
            msg = exists_errmsg.format(self.data_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("dataname given does not exist in bucket.")
        elif not utilsparam.s3.exists(self.bucket_name,self.config_name): 
            msg = exists_errmsg.format(self.config_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("configname given does not exist in bucket.")
        ###########################

        ## Now get the actual paths to relevant data from the foldername: 

        self.filenames = utilsparam.s3.extract_files(self.bucket_name,self.data_name,ext = None) 
        assert len(self.filenames) > 0, "we must have data to analyze."

    def process_inputs(self):
        """ Initiates Processing On Previously Acquired EC2 Instance. This version requires that you include a config (fourth) argument """
        print(self.bucket_name,'bucket name')
        print(self.filenames,'filenames')
        print(os.environ['OUTDIR'],'outdir')
        print(os.environ['COMMAND'],'command')
        try: 
            os.environ['COMMAND'].format("a","b","c","d")
        except IndexError as ie:
            msg = "not enough arguments in the COMMAND argument."
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("Not the correct format for arguments.")
     

        ## Should we vectorize the log here? 
        outpath_full = os.path.join(os.environ['OUTDIR'],self.jobname)
        [self.logger.append("Sending command: {}".format(
            os.environ['COMMAND'].format(
                self.bucket_name, filename, outpath_full, self.config_name
            )
        )) for filename in self.filenames]
        print([os.environ['COMMAND'].format(
              self.bucket_name, filename, outpath_full, self.config_name
              ) for filename in self.filenames],"command send")
        for f,filename in enumerate(self.filenames):
            response = utilsparam.ssm.execute_commands_on_linux_instances(
                commands=[os.environ['COMMAND'].format(
                    self.bucket_name, filename, outpath_full, self.config_name
                    )], # TODO: variable outdir as option
                instance_ids=[self.instances[f].instance_id],
                working_dirs=[os.environ['WORKING_DIRECTORY']],
                log_bucket_name=self.bucket_name,
                log_path=os.path.join(self.jobpath,'internal_ec2_logs')
                )
            self.logger.initialize_datasets_dev(filename,self.instances[f].instance_id,response["Command"]["CommandId"])

## Gets acquire, start, monitor. 
class Submission_Launch_log_demo():
    """
    Specific lambda for purposes of demo. 
    """
    def __init__(self,bucket_name,key,time):
        ## Initialize as before:
        # Get Upload Location Information
        self.bucket_name = bucket_name
        ## Get directory above the input directory. 
        self.path = re.findall('.+?(?=/'+os.environ["INDIR"]+')',key)[0] 
        ## Now add in the time parameter: 
        self.time = time
        ## We will index by the submit file name prefix if it exists: 
        submit_search = re.findall('.+?(?=/submit.json)',os.path.basename(key))
        try:
            submit_name = submit_search[0]
        except IndexError as e:
            ## If the filename is just "submit.json, we just don't append anything to the job name. "
            submit_name = ""
            
        ## Now we're going to get the path to the results directory: 
        self.jobname = "job"+submit_name+'epi_demo'
        jobpath = os.path.join(self.path,os.environ['OUTDIR'],self.jobname)
        self.jobpath = jobpath
        ## Reset this directory
        create_jobdir  = utilsparam.s3.mkdir_reset(self.bucket_name, os.path.join(self.path,os.environ['OUTDIR']),self.jobname)
        
        self.logger = utilsparam.s3.JobLogger_demo(self.bucket_name, self.jobpath)
        self.logger.append("Initializing EPI analysis: Parameter search for 2D LDS.")
        self.logger.write()
        #self.out_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.OUTDIR)
        #self.in_path = utilsparam.s3.mkdir(self.bucket_name, self.path, config.INDIR)

        # Load Content Of Submit File 
        submit_file = utilsparam.s3.load_json(bucket_name, key)
        ## Check what instance we should use. 
        try:
            self.instance_type = submit_file['instance_type'] # TODO default option from config
        except KeyError as ke: 
            msg = "Using default instance type {} from config file".format(os.environ["INSTANCE_TYPE"])
            self.instance_type = os.environ["INSTANCE_TYPE"]
            ## Log this message.- not crucial for logging. 
            #self.logger.append(msg)
            #self.logger.write()

        ## These next two check that the submit file is correctly formatted
        ## Check that we have a dataname field:
        submit_errmsg = "INPUT ERROR: Submit file does not contain field {}, needed to analyze data."
        try: 
            self.data_name = submit_file['dataname'] # TODO validate extensions 
        except KeyError as ke:

            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError("Missing data name to analyze")

        try:
            self.config_name = submit_file["configname"] 
            self.logger.assign_config(self.config_name)
        except KeyError as ke:
            print(submit_errmsg.format(ke))
            ## Write to logger
            self.logger.append(submit_errmsg.format(ke))
            self.logger.write()
            ## Now raise an exception to halt processing, because this is a catastrophic error.  
            raise ValueError(os.environ["MISSING_CONFIG_ERROR"])

        self.logger.append("EPI analysis request detected with dataset {}, config file {}. Reading EPI blueprint.".format(self.data_name,self.config_name))
        self.logger.write()

        ## Check that we have the actual data in the bucket.  
        exists_errmsg = "INPUT ERROR: S3 Bucket does not contain {}"
        if not utilsparam.s3.exists(self.bucket_name,self.data_name): 
            msg = exists_errmsg.format(self.data_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("dataname given does not exist in bucket.")
        elif not utilsparam.s3.exists(self.bucket_name,self.config_name): 
            msg = exists_errmsg.format(self.config_name)
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("configname given does not exist in bucket.")
        ###########################

        ## Now get the actual paths to relevant data from the foldername: 

        self.filenames = utilsparam.s3.extract_files(self.bucket_name,self.data_name,ext = None) 
        assert len(self.filenames) > 0, "we must have data to analyze."

    def acquire_instance(self):
        """ Acquires & Starts New EC2 Instances Of The Requested Type & AMI. Specialized certificate messages. """
        instances = []
        nb_instances = len(self.filenames)

        ## Check how many instances are running. 
        active = utilsparam.ec2.count_active_instances(self.instance_type)
        ## Ensure that we have enough bandwidth to support this request:
        if active +nb_instances < int(os.environ['DEPLOY_LIMIT']):
            pass
        else:
            self.logger.append("RESOURCE ERROR: Instance requests greater than pipeline bandwidth. Please contact NCAP administrator.")
        

        for i in range(nb_instances):
            instance = utilsparam.ec2.launch_new_instance(
            instance_type=self.instance_type, 
            ami=os.environ['AMI'],
            logger= []# self.logger
            )
            instances.append(instance)
        self.logger.append("Setting up {} EPI infrastructures from blueprint, please wait...".format(nb_instances))
        self.instances = instances

    def start_instance(self):
        """ Starts new instances if stopped. We write a special loop for this one because we only need a single 60 second pause for all the intances, not one for each in serial. Specialized certificate messages. """
        utilsparam.ec2.start_instances_if_stopped(
            instances=self.instances,
            logger=[]#self.logger
        )
        self.logger.append("Created {} EPI infrastructures with 4 cpus, 16 GB memory ".format(len(self.filenames)))

    def process_inputs(self):
        """ Initiates Processing On Previously Acquired EC2 Instance. This version requires that you include a config (fourth) argument """
        print(self.bucket_name,'bucket name')
        print(self.filenames,'filenames')
        print(os.environ['OUTDIR'],'outdir')
        print(os.environ['COMMAND'],'command')
        try: 
            os.environ['COMMAND'].format("a","b","c","d")
        except IndexError as ie:
            msg = "not enough arguments in the COMMAND argument."
            self.logger.append(msg)
            self.logger.write()
            raise ValueError("Not the correct format for arguments.")
     

        ## Should we vectorize the log here? 
        outpath_full = os.path.join(os.environ['OUTDIR'],self.jobname)

        #[self.logger.append("Starting analysis with parameter set {}, dataset {}".format(
        #    f+1,
        #    filename
        #    )
        #) for f,filename in enumerate(self.filenames)]
        #[self.logger.append("Starting analysis with parameter set {}: {}".format(
        #    f+1,
        #    os.environ['COMMAND'].format(
        #        self.bucket_name, filename, outpath_full, self.config_name
        #    )
        #)) for f,filename in enumerate(self.filenames)]
        print([os.environ['COMMAND'].format(
              self.bucket_name, filename, outpath_full, self.config_name
              ) for filename in self.filenames],"command send")
        for f,filename in enumerate(self.filenames):
            response = utilsparam.ssm.execute_commands_on_linux_instances(
                commands=[os.environ['COMMAND'].format(
                    self.bucket_name, filename, outpath_full, self.config_name
                    )], # TODO: variable outdir as option
                instance_ids=[self.instances[f].instance_id],
                working_dirs=[os.environ['WORKING_DIRECTORY']],
                log_bucket_name=self.bucket_name,
                log_path=os.path.join(self.jobpath,'internal_ec2_logs')
                )
            self.logger.initialize_datasets_dev(filename,self.instances[f].instance_id,response["Command"]["CommandId"])
            self.logger.append("Starting analysis {} with parameter set {}".format(f+1,os.path.basename(filename)))
            self.logger.write()
        self.logger.append("All jobs submitted. Processing...")


    ## Declare rules to monitor the states of these instances.  
    def put_instance_monitor_rule(self): 
        """ For multiple datasets."""
        for instance in self.instances:
            self.logger.append('Setting up monitoring on instance '+str(instance))
            ## First declare a monitoring rule for this instance: 
            ruledata,rulename = utilsparam.events.put_instance_rule(instance.instance_id)
            arn = ruledata['RuleArn']
            ## Now attach it to the given target
            targetdata = utilsparam.events.put_instance_target(rulename) 

def process_upload_log_dev(bucket_name, key,time):
    """ 
    Updated version that can handle config files. 
    Inputs:
    key: absolute path to created object within bucket.
    bucket: name of the bucket within which the upload occurred.
    time: the time at which the upload event happened. 
    """

    ## Conditionals for different deploy configurations: 
    ## First check if we are launching a new instance or starting an existing one. 
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ['LAUNCH'] == 'true':
        ## Now check how many datasets we have
        submission = Submission_Launch_log_dev(bucket_name, key, time)
    elif os.environ["LAUNCH"] == 'false':
        raise NotImplementedError("This option not available for configs. ")
    print("acquiring")
    submission.acquire_instance()
    print('writing0')
    submission.logger.write()
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ["MONITOR"] == "true":
        print('setting up monitor')
        submission.put_instance_monitor_rule()
    elif os.environ["MONITOR"] == "false":
        print("skipping monitor")
    print('writing1')
    submission.logger.write()
    print('starting')
    submission.start_instance()
    print('writing2')
    print('sending')
    submission.process_inputs()
    print("writing3")
    submission.logger.write()

def process_upload_log_demo(bucket_name, key,time):
    """ 
    Updated version that can handle config files. 
    Inputs:
    key: absolute path to created object within bucket.
    bucket: name of the bucket within which the upload occurred.
    time: the time at which the upload event happened. 
    """

    ## Conditionals for different deploy configurations: 
    ## First check if we are launching a new instance or starting an existing one. 
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ['LAUNCH'] == 'true':
        ## Now check how many datasets we have
        submission = Submission_Launch_log_demo(bucket_name, key, time)
    elif os.environ["LAUNCH"] == 'false':
        raise NotImplementedError("This option not available for configs. ")
    print("acquiring")
    submission.acquire_instance()
    print('writing0')
    submission.logger.write()
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ["MONITOR"] == "true":
        print('setting up monitor')
        submission.put_instance_monitor_rule()
    elif os.environ["MONITOR"] == "false":
        print("skipping monitor")
    print('writing1')
    submission.logger.write()
    print('starting')
    submission.start_instance()
    print('writing2')
    submission.logger.write()
    print('sending')
    submission.process_inputs()
    print("writing3")
    submission.logger.write()

    submission.logger.write()
## New 2/11: for disjoint data and upload buckets. 
def process_upload_log_test(bucket_name, key,time):
    """ 
    Updated version that can handle config files. 
    Inputs:
    key: absolute path to created object within bucket.
    bucket: name of the bucket within which the upload occurred.
    time: the time at which the upload event happened. 
    """

    ## Conditionals for different deploy configurations: 
    ## First check if we are launching a new instance or starting an existing one. 
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ['LAUNCH'] == 'true':
        ## Now check how many datasets we have
        submission = Submission_Launch_log_test(bucket_name, key, time)
    elif os.environ["LAUNCH"] == 'false':
        raise NotImplementedError("This option not available for configs. ")
    print("acquiring")
    submission.acquire_instance()
    print('writing0')
    submission.inputlogger.write()
    submission.submitlogger.write()
    ## NOTE: IN LAMBDA,  JSON BOOLEANS ARE CONVERTED TO STRING
    if os.environ["MONITOR"] == "true":
        print('setting up monitor')
        submission.put_instance_monitor_rule()
    elif os.environ["MONITOR"] == "false":
        print("skipping monitor")
    print('writing1')
    submission.inputlogger.write()
    submission.submitlogger.write()
    print('starting')
    submission.start_instance()
    print('writing2')
    print('sending')
    submission.process_inputs()
    print("writing3")
    submission.inputlogger.write()
    submission.submitlogger.write()
    
def handler_log_dev(event,context):
    """
    Newest version of handler that logs outputs to a subfolder of the result folder that is indexed by the job submission date and the submit name.
    """
    
    for record in event['Records']:
        time = record['eventTime']
        bucket_name = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        print("handler_params",bucket_name,key,time)
        print(event,context,'event, context')
        process_upload_log_dev(bucket_name, key, time);

def handler_log_demo(event,context):
    """
    Newest version of handler that logs outputs to a subfolder of the result folder that is indexed by the job submission date and the submit name.
    """
    
    for record in event['Records']:
        time = record['eventTime']
        bucket_name = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        print("handler_params",bucket_name,key,time)
        print(event,context,'event, context')
        process_upload_log_demo(bucket_name, key, time);

def handler_log_test(event,context):
    """
    E
    """
    
    for record in event['Records']:
        time = record['eventTime']
        bucket_name = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        print("handler_params",bucket_name,key,time)
        print(event,context,'event, context')
        process_upload_log_test(bucket_name, key, time);
