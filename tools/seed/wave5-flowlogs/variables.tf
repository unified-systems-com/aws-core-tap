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
  description = "The window each run summarises, ending when it runs. Ignored when window_start is set."
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
  description = "The fixed window's end, as YYYY-MM-DDTHH:MM:SSZ. Empty means the time the query runs."
  type        = string
  default     = ""

  validation {
    condition     = var.window_end == "" || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.window_end))
    error_message = "window_end must be empty or YYYY-MM-DDTHH:MM:SSZ."
  }
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
  description = "When the summarising query runs (EventBridge Scheduler syntax)."
  type        = string
  default     = "rate(1 hour)"
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
