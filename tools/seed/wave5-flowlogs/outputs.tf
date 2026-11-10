# What a run needs to drive and check the trial. None of these holds the account number.

output "summarise_sql" {
  description = "The summarising query for a run by hand at run_time, as rendered from the filter variables; null without a run_time."
  value       = local.summarise_sql
}

output "summarise_sql_scheduled" {
  description = "The query the schedule runs; Scheduler substitutes its scheduled time for the placeholder."
  value       = local.summarise["scheduled"]
}

output "workgroup" {
  value = aws_athena_workgroup.flows.name
}

output "database" {
  value = aws_glue_catalog_database.flows.name
}

output "work_bucket" {
  value = aws_s3_bucket.work.bucket
}

output "hosts" {
  description = "The two instances, for the host filters."
  value = {
    server = {
      instance_id  = aws_instance.server.id
      interface_id = aws_instance.server.primary_network_interface_id
      address      = aws_instance.server.private_ip
    }
    client = {
      instance_id  = aws_instance.client.id
      interface_id = aws_instance.client.primary_network_interface_id
      address      = aws_instance.client.private_ip
    }
  }
}
