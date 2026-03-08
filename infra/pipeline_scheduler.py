"""
Lambda function: Start EC2 instance, run pipeline via SSM, then stop instance.

Triggered by EventBridge Scheduler on a schedule (twice daily).

Environment variables:
  INSTANCE_ID     — the EC2 instance to run the pipeline on
  SNS_TOPIC_ARN   — (optional) SNS topic for failure notifications
"""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")
sns = boto3.client("sns")

INSTANCE_ID = os.environ["INSTANCE_ID"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
PIPELINE_COMMAND = "sudo -u ubuntu bash -l -c '/home/ubuntu/conflict-resolver/run-pipeline.sh'"
# Max time to wait for each phase (must sum to well under 900s Lambda max)
INSTANCE_START_TIMEOUT = 90   # seconds
SSM_AGENT_TIMEOUT = 90
PIPELINE_TIMEOUT = 480
# Total: 660s, leaving 240s margin before Lambda's 900s hard limit


def lambda_handler(event, context):
    logger.info("Starting pipeline run for instance %s", INSTANCE_ID)

    we_started_it = False

    try:
        # 1. Start the instance (track whether we started it)
        we_started_it = start_instance()

        # 2. Wait for SSM agent to be online
        wait_for_ssm_agent()

        # 3. Run the pipeline via SSM
        run_pipeline()

    except Exception as e:
        logger.exception("Pipeline run failed")
        notify_failure(str(e))
        raise

    finally:
        # Only stop the instance if we started it
        if we_started_it:
            stop_instance()
        else:
            logger.info("Instance was already running before invocation, leaving it running")

    logger.info("Pipeline run complete, instance stopping")
    return {"statusCode": 200, "body": "Pipeline run complete"}


def start_instance():
    """Start the EC2 instance and wait for it to be running.

    Returns True if we started the instance, False if it was already running.
    """
    state = get_instance_state()

    if state == "running":
        logger.info("Instance already running (manual session?), will not stop on exit")
        return False

    if state != "stopped":
        raise RuntimeError(f"Instance in unexpected state: {state}")

    logger.info("Starting instance...")
    ec2.start_instances(InstanceIds=[INSTANCE_ID])

    # Wait for running state
    deadline = time.time() + INSTANCE_START_TIMEOUT
    while time.time() < deadline:
        if get_instance_state() == "running":
            logger.info("Instance is running")
            return True
        time.sleep(5)

    raise TimeoutError("Instance did not reach running state in time")


def wait_for_ssm_agent():
    """Wait for the SSM agent on the instance to come online."""
    logger.info("Waiting for SSM agent...")
    deadline = time.time() + SSM_AGENT_TIMEOUT
    while time.time() < deadline:
        try:
            resp = ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [INSTANCE_ID]}]
            )
            instances = resp.get("InstanceInformationList", [])
            if instances and instances[0].get("PingStatus") == "Online":
                logger.info("SSM agent is online")
                return
        except Exception:
            pass
        time.sleep(10)

    raise TimeoutError("SSM agent did not come online in time")


def run_pipeline():
    """Execute the pipeline script via SSM RunCommand."""
    logger.info("Sending pipeline command via SSM...")
    resp = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [
            # Defense in depth: cancel any pending shutdown from old cron
            "sudo shutdown -c 2>/dev/null || true",
            PIPELINE_COMMAND,
        ]},
        TimeoutSeconds=PIPELINE_TIMEOUT,
    )
    command_id = resp["Command"]["CommandId"]
    logger.info("SSM command sent: %s", command_id)

    # Poll for completion
    deadline = time.time() + PIPELINE_TIMEOUT
    while time.time() < deadline:
        time.sleep(15)
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id, InstanceId=INSTANCE_ID
            )
            status = result["Status"]
            if status in ("Success",):
                logger.info("Pipeline completed successfully")
                return
            if status in ("Failed", "TimedOut", "Cancelled"):
                stdout = result.get("StandardOutputContent", "")
                stderr = result.get("StandardErrorContent", "")
                logger.error("Pipeline failed (status=%s)\nstdout: %s\nstderr: %s",
                             status, stdout[-4000:], stderr[-4000:])
                raise RuntimeError(f"Pipeline command failed with status: {status}")
        except ssm.exceptions.InvocationDoesNotExist:
            pass  # Command not yet delivered

    raise TimeoutError("Pipeline did not complete in time")


def stop_instance():
    """Stop the EC2 instance."""
    state = get_instance_state()
    if state in ("stopped", "stopping"):
        logger.info("Instance already %s", state)
        return

    logger.info("Stopping instance...")
    ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    logger.info("Stop command sent")


def get_instance_state():
    resp = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"]


def notify_failure(error_message):
    """Send failure notification via SNS if topic is configured."""
    if not SNS_TOPIC_ARN:
        return
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Conflict Resolver Pipeline Failed",
            Message=f"Pipeline run failed for instance {INSTANCE_ID}.\n\nError: {error_message}",
        )
        logger.info("Failure notification sent to SNS")
    except Exception:
        logger.exception("Failed to send SNS notification")
