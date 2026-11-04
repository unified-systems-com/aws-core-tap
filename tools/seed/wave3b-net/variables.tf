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
