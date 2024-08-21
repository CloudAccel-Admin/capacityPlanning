## python awsCloudWatchAgent_Installation.py --region <Region, ex: us-west-2> --instance-ids <instance-id-1> <instance-id-2> --aws-package AmazonCloudWatch-ManageAgent'

import boto3
import argparse
import time
import json

def create_ssm_client(region_name):
    return boto3.client('ssm', region_name=region_name)

def create_ec2_client():
    return boto3.client('ec2')

def is_instance_running(ec2_client, instance_id):
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        state = response['Reservations'][0]['Instances'][0]['State']['Name']
        return state == 'running'
    except ec2_client.exceptions.ClientError as e:
        return False, str(e)

def send_update_ssm_agent_command(ssm_client, instance_ids):
    document_name = 'AWS-UpdateSSMAgent'
    try:
        response = ssm_client.send_command(
            DocumentName=document_name,
            Targets=[
                {
                    'Key': 'InstanceIds',
                    'Values': instance_ids
                }
            ],
            Parameters={
                'version': [''],
                'allowDowngrade': ['false']
            },
            TimeoutSeconds=600,
            MaxConcurrency='50',
            MaxErrors='0'
        )
        command_id = response['Command']['CommandId']
        return True, command_id, None
    except ssm_client.exceptions.ClientError as e:
        return False, None, str(e)

def send_configure_aws_package_command(ssm_client, instance_ids):
    document_name = 'AWS-ConfigureAWSPackage'
    document_version = '$LATEST'
    parameters = {
        'action': ['Install'],
        'installationType': ['Uninstall and reinstall'],
        'name': ['AmazonCloudWatchAgent'],
        'version': [''],
        'additionalArguments': ['{}']
    }
    
    try:
        response = ssm_client.send_command(
            DocumentName=document_name,
            DocumentVersion=document_version,
            Targets=[
                {
                    'Key': 'InstanceIds',
                    'Values': instance_ids
                }
            ],
            Parameters=parameters,
            TimeoutSeconds=600,
            MaxConcurrency='50',
            MaxErrors='0'
        )
        command_id = response['Command']['CommandId']
        return True, command_id, None
    except ssm_client.exceptions.ClientError as e:
        return False, None, str(e)

def send_custom_ssm_command(ssm_client, instance_ids, document_name):
    parameters = {
        'action': ['configure'],
        'mode': ['ec2'],
        'optionalConfigurationSource': ['default'],
        'optionalConfigurationLocation': [''],
        'optionalRestart': ['yes']
    }
    
    try:
        response = ssm_client.send_command(
            DocumentName=document_name,
            Targets=[
                {
                    'Key': 'InstanceIds',
                    'Values': instance_ids
                }
            ],
            Parameters=parameters,
            TimeoutSeconds=600,
            MaxConcurrency='50',
            MaxErrors='0'
        )
        command_id = response['Command']['CommandId']
        return True, command_id, None
    except ssm_client.exceptions.ClientError as e:
        return False, None, str(e)

def check_command_status(ssm_client, command_id, instance_ids):
    while True:
        time.sleep(10)  # Poll every 10 seconds
        try:
            response = ssm_client.list_commands(
                CommandId=command_id,
                InstanceId=instance_ids[0]
            )
            status = response['Commands'][0]['Status']
            if status in ['Success', 'Failed', 'Cancelled']:
                return status
        except ssm_client.exceptions.ClientError as e:
            return f"Error checking status: {str(e)}"

def check_iam_role_attached(ec2_client, instance_id, role_name):
    try:
        response = ec2_client.describe_iam_instance_profile_associations(
            Filters=[
                {
                    'Name': 'instance-id',
                    'Values': [instance_id]
                }
            ]
        )
        if response['IamInstanceProfileAssociations']:
            for profile in response['IamInstanceProfileAssociations']:
                if profile['IamInstanceProfile']['Arn'].split('/')[-1] == role_name:
                    return True, None  # Role already attached
            return False, "Different role attached."
        else:
            return False, "No IAM role attached."
    except ec2_client.exceptions.ClientError as e:
        return False, str(e)

def attach_iam_role_to_instance(ec2_client, instance_id, role_name):
    try:
        response = ec2_client.associate_iam_instance_profile(
            IamInstanceProfile={
                'Name': role_name
            },
            InstanceId=instance_id
        )
        return True, None
    except ec2_client.exceptions.ClientError as e:
        return False, str(e)

def main():
    parser = argparse.ArgumentParser(description='Send SSM commands and attach IAM roles to EC2 instances.')
    parser.add_argument('--region', required=True, help='AWS region')
    parser.add_argument('--instance-ids', required=True, nargs='+', help='List of EC2 instance IDs')
    parser.add_argument('--aws-package', required=True, help='Custom SSM document name')

    args = parser.parse_args()

    ssm_client = create_ssm_client(args.region)
    ec2_client = create_ec2_client()

    results = []
    role_name = 'CloudWatchAgentServerRole'  # Hardcoded IAM role name
    overall_result = True  # Track overall success or failure

    for instance_id in args.instance_ids:
        instance_result = {"instance_id": instance_id, "warning": None}
        
        # Check if the instance is running
        if not is_instance_running(ec2_client, instance_id):
            instance_result["warning"] = "Instance is not in a running state."
            overall_result = False  # Mark overall result as failed
            results.append(instance_result)
            continue

        # Check if the IAM role is already attached
        role_attached, message = check_iam_role_attached(ec2_client, instance_id, role_name)
        if role_attached:
            instance_result["warning"] = "IAM role is already attached."
        else:
            # Attach IAM role to EC2 instance
            success, warning = attach_iam_role_to_instance(ec2_client, instance_id, role_name)
            if not success:
                instance_result["warning"] = f"Failed to attach IAM role: {warning}"
                overall_result = False  # Mark overall result as failed

        # Proceed with SSM commands only if role was already attached or successfully attached
        if not instance_result.get("warning"):
            # Send the hardcoded Update SSM Agent command
            success, command_id, warning = send_update_ssm_agent_command(ssm_client, [instance_id])
            if not success:
                instance_result["warning"] = f"Update SSM Agent command failed: {warning}"
                overall_result = False  # Mark overall result as failed
            else:
                status = check_command_status(ssm_client, command_id, [instance_id])
                if status != 'Success':
                    instance_result["warning"] = f"Update SSM Agent command was not successful. Status: {status}"
                    overall_result = False  # Mark overall result as failed

            # Send the Configure AWS Package command if the first command was successful
            if not instance_result.get("warning"):
                success, command_id, warning = send_configure_aws_package_command(ssm_client, [instance_id])
                if not success:
                    instance_result["warning"] = f"Configure AWS Package command failed: {warning}"
                    overall_result = False  # Mark overall result as failed
                else:
                    status = check_command_status(ssm_client, command_id, [instance_id])
                    if status != 'Success':
                        instance_result["warning"] = f"Configure AWS Package command was not successful. Status: {status}"
                        overall_result = False  # Mark overall result as failed

            # Send the custom SSM command with the document name provided via command line if the previous command was successful
            if not instance_result.get("warning"):
                success, command_id, warning = send_custom_ssm_command(ssm_client, [instance_id], args.aws_package)
                if not success:
                    instance_result["warning"] = f"Custom SSM command failed: {warning}"
                    overall_result = False  # Mark overall result as failed
                else:
                    status = check_command_status(ssm_client, command_id, [instance_id])
                    if status != 'Success':
                        instance_result["warning"] = f"Custom SSM command was not successful. Status: {status}"
                        overall_result = False  # Mark overall result as failed

        results.append(instance_result)

    # Output the results as a JSON object
    output = {
        "result": str(overall_result).lower(),
        "taskoutput": results
    }
    print(json.dumps(output, indent=4))

if __name__ == "__main__":
    main()
