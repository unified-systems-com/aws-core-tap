variable "run_id" {
  description = "Identifies this run. Becomes the tap-seed-run tag and part of every name. Required; no default."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.run_id))
    error_message = "run_id must be 3 to 12 lowercase letters or digits (it is part of S3 bucket and IAM names)."
  }
}

variable "expected_account_id" {
  description = "The 12-digit account this wave may act in. Supplied at run time (TF_VAR_expected_account_id); never written to a file. The provider refuses any other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must be 12 digits."
  }
}

variable "profile" {
  description = "AWS CLI profile of the seeder identity. Credentials are read from the CLI configuration, never from files in this repository."
  type        = string
  default     = "tap-seeder-git-serious"
}

# --- The summarising query's filters (aws-core-tap#218). Empty means no filter. Each value is validated so that it can
# only be what it names: the values are written into SQL, so nothing that could close a quote may pass. ---

variable "filter_interface_ids" {
  description = "Only flows seen on these network interfaces (eni-...). Combined with the other host filters by OR."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.filter_interface_ids : can(regex("^eni-[0-9a-f]{8,17}$", v))])
    error_message = "Each filter_interface_ids value must look like eni-0123456789abcdef0."
  }
}

variable "filter_instance_ids" {
  description = "Only flows whose interface belongs to these instances (i-...). Combined with the other host filters by OR."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.filter_instance_ids : can(regex("^i-[0-9a-f]{8,17}$", v))])
    error_message = "Each filter_instance_ids value must look like i-0123456789abcdef0."
  }
}

variable "filter_addresses" {
  description = "Only flows to or from these IPv4 addresses. Combined with the other host filters by OR."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.filter_addresses : can(cidrhost("${v}/32", 0))])
    error_message = "Each filter_addresses value must be one IPv4 address."
  }
}

# Source and destination mean the conversation's client (who opened it) and server, as the query decides them, not a
# packet's srcaddr and dstaddr: a reply's packets travel server to client but belong to the same conversation.

variable "filter_sources" {
  description = "Only conversations opened by one of these IPv4 addresses (the client)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.filter_sources : can(cidrhost("${v}/32", 0))])
    error_message = "Each filter_sources value must be one IPv4 address."
  }
}

variable "filter_destinations" {
  description = "Only conversations whose server is one of these IPv4 addresses."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.filter_destinations : can(cidrhost("${v}/32", 0))])
    error_message = "Each filter_destinations value must be one IPv4 address."
  }
}

variable "filter_pairs" {
  description = "Only conversations between these client and server pairs, each {source = \"10.0.0.1\", destination = \"10.0.0.2\"}. A pair is directed; list both orders to match either."
  type        = list(object({ source = string, destination = string }))
  default     = []

  validation {
    condition     = alltrue([for p in var.filter_pairs : can(cidrhost("${p.source}/32", 0)) && can(cidrhost("${p.destination}/32", 0))])
    error_message = "Each filter_pairs entry must be {source, destination}, each one IPv4 address."
  }
}

variable "filter_ports" {
  description = "Only flows whose source or destination port is one of these."
  type        = list(number)
  default     = []

  validation {
    condition     = alltrue([for p in var.filter_ports : p == floor(p) && p >= 0 && p <= 65535])
    error_message = "Each filter_ports value must be a whole number from 0 to 65535."
  }
}

variable "lookback_hours" {
  description = "The window each run summarises, in hours, ending at window_end. Ignored when window_start is set."
  type        = number
  default     = 1

  validation {
    condition     = var.lookback_hours == floor(var.lookback_hours) && var.lookback_hours >= 1 && var.lookback_hours <= 744
    error_message = "lookback_hours must be a whole number of hours from 1 to 744 (31 days)."
  }
}

variable "window_start" {
  description = "A fixed window instead of a lookback: its start, as YYYY-MM-DDTHH:MM:SSZ. Empty for the lookback."
  type        = string
  default     = ""

  validation {
    condition     = var.window_start == "" || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.window_start))
    error_message = "window_start must be empty or YYYY-MM-DDTHH:MM:SSZ."
  }
}

variable "window_end" {
  description = "The fixed window's end, as YYYY-MM-DDTHH:MM:SSZ. Empty means the hour boundary at or before run_time less lag_minutes."
  type        = string
  default     = ""

  validation {
    condition     = var.window_end == "" || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.window_end))
    error_message = "window_end must be empty or YYYY-MM-DDTHH:MM:SSZ."
  }
}

variable "lag_minutes" {
  description = "How far behind the run's time the window ends, because flow log records reach S3 several minutes late (about 10, best effort). The end is then rounded down to the hour, so runs in the same hour summarise the same window."
  type        = number
  default     = 20

  validation {
    condition     = var.lag_minutes == floor(var.lag_minutes) && var.lag_minutes >= 0 && var.lag_minutes <= 1440
    error_message = "lag_minutes must be a whole number from 0 to 1440."
  }
}

variable "run_time" {
  description = "The run's time, as YYYY-MM-DDTHH:MM:SSZ, for a run by hand: it names the run's output prefix and, with no fixed window_end, places the window. The schedule supplies its own scheduled time instead. Empty renders no hand-run query."
  type        = string
  default     = ""

  validation {
    condition     = var.run_time == "" || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.run_time))
    error_message = "run_time must be empty or YYYY-MM-DDTHH:MM:SSZ."
  }
}

variable "output_name" {
  description = "The top-level prefix in the work bucket a run writes under. The schedule always writes under summaries; a focused extraction by hand should name its own, so it never mixes with the hourly summaries."
  type        = string
  default     = "summaries"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,39}$", var.output_name)) && var.output_name != "athena-results"
    error_message = "output_name must be 1 to 40 lowercase letters, digits or hyphens, and not athena-results."
  }
}

variable "newer_fields" {
  description = "Also log pkt-src-aws-service, pkt-dst-aws-service (version 5) and next-hop-interface-id (version 11). Turn off where the region rejects a field; the query reads them as null either way."
  type        = bool
  default     = true
}

variable "aggregation_interval" {
  description = "Seconds a flow log record aggregates: 60 for a trial (records arrive sooner), 600 for fewer records."
  type        = number
  default     = 60

  validation {
    condition     = contains([60, 600], var.aggregation_interval)
    error_message = "aggregation_interval must be 60 or 600."
  }
}

variable "schedule_expression" {
  description = "When the summarising query runs (EventBridge Scheduler syntax). Once an hour, at a minute past lag_minutes, gives one run per window; a second run in the same hour summarises the same window again under its own prefix."
  type        = string
  default     = "cron(25 * * * ? *)"
}

variable "schedule_state" {
  description = "ENABLED or DISABLED. A trial can run the query by hand and leave the schedule off."
  type        = string
  default     = "DISABLED"

  validation {
    condition     = contains(["ENABLED", "DISABLED"], var.schedule_state)
    error_message = "schedule_state must be ENABLED or DISABLED."
  }
}
