##python awsCloudWatchAgent_Installation.py --region us-east-2 --instance-ids i-075d77d4c3e7acec5 i-035613d48cf949cc7 --aws-package AmazonCloudWatch-ManageAgent

import boto3
import argparse
import time

def create_ssm_client(region_name):
    return boto3.client('ssm', region_name=region_name)

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
        print("Update SSM Agent command sent successfully.")
        print("Command ID:", command_id)
        return command_id
    except ssm_client.exceptions.ClientError as e:
        print(f"Failed to send Update SSM Agent command: {e}")
        return None

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
        print("Configure AWS Package command sent successfully.")
        print("Command ID:", command_id)
        return command_id
    except ssm_client.exceptions.ClientError as e:
        print(f"Failed to send Configure AWS Package command: {e}")
        return None

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
        print("Custom command sent successfully.")
        print("Command ID:", command_id)
        return command_id
    except ssm_client.exceptions.ClientError as e:
        print(f"Failed to send custom command: {e}")
        return None

def check_command_status(ssm_client, command_id, instance_ids):
    while True:
        time.sleep(10)  # Poll every 10 seconds
        try:
            response = ssm_client.list_commands(
                CommandId=command_id,
                InstanceId=instance_ids[0]
            )
            status = response['Commands'][0]['Status']
            print(f"Command {command_id} status: {status}")
            if status in ['Success', 'Failed', 'Cancelled']:
                return status
        except ssm_client.exceptions.ClientError as e:
            print(f"Failed to check command status: {e}")
            return None

def create_ec2_client():
    return boto3.client('ec2')

def attach_iam_role_to_instance(ec2_client, instance_ids):
    role_name = 'CloudWatchAgentServerRole'  # Hardcoded IAM role name
    try:
        for instance_id in instance_ids:
            response = ec2_client.associate_iam_instance_profile(
                IamInstanceProfile={
                    'Name': role_name
                },
                InstanceId=instance_id
            )
            print(f"Successfully attached role {role_name} to instance {instance_id}.")
            print("Response:", response)
    except ec2_client.exceptions.ClientError as e:
        print(f"Failed to attach role to instance: {e}")

def main():
    parser = argparse.ArgumentParser(description='Send SSM commands and attach IAM roles to EC2 instances.')
    parser.add_argument('--region', required=True, help='AWS region')
    parser.add_argument('--instance-ids', required=True, nargs='+', help='List of EC2 instance IDs')
    parser.add_argument('--aws-package', required=True, help='Custom SSM document name')

    args = parser.parse_args()

    ssm_client = create_ssm_client(args.region)
    ec2_client = create_ec2_client()

    # Send the hardcoded commands
    update_ssm_command_id = send_update_ssm_agent_command(ssm_client, args.instance_ids)
    if update_ssm_command_id:
        status = check_command_status(ssm_client, update_ssm_command_id, args.instance_ids)
        if status != 'Success':
            print("Update SSM Agent command failed or was not successful. Exiting.")
            return

    configure_package_command_id = send_configure_aws_package_command(ssm_client, args.instance_ids)
    if configure_package_command_id:
        status = check_command_status(ssm_client, configure_package_command_id, args.instance_ids)
        if status != 'Success':
            print("Configure AWS Package command failed or was not successful. Exiting.")
            return

    # Send the custom command with the document name provided via command line
    custom_ssm_command_id = send_custom_ssm_command(ssm_client, args.instance_ids, args.aws_package)
    if custom_ssm_command_id:
        status = check_command_status(ssm_client, custom_ssm_command_id, args.instance_ids)
        if status != 'Success':
            print("Custom command failed or was not successful. Exiting.")
            return

    # Attach IAM role to EC2 instances
    attach_iam_role_to_instance(ec2_client, args.instance_ids)

if __name__ == "__main__":
    main()
