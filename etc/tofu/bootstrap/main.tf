terraform {
  backend "gcs" {
    bucket = "oar-gsl-hpc-aw-0103-state"
    prefix = "bootstrap"
  }
  required_providers {
    google = {
      source = "opentffoundation/google"
      version = "7.22.0"
    }
  }
}

provider "google" {
  project = "oar-gsl-hpc-aw-0103"
}

locals {
  principals = toset([
    "user:christina.holt@noaa.gov",
    "user:emily.l.carpenter@noaa.gov",
    "user:paul.madden@noaa.gov",
  ])
}

resource "google_project_service" "cloud_storage" {
  service = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "state" {
  name = "oar-gsl-hpc-aw-0103-state"
  location = "us-central1"
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
  depends_on = [google_project_service.cloud_storage]
}

resource "google_storage_bucket_iam_member" "state_principals" {
  for_each = local.principals
  bucket = google_storage_bucket.state.name
  role = "roles/storage.objectUser"
  member = each.value
}

#resource "google_project_service" "batch" {
#  service = "batch.googleapis.com"
#  disable_on_destroy = true
#  depends_on = [
#    google_project_service.compute
#  ]
#}

resource "google_project_service" "compute" {
  service = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "logging" {
  service = "logging.googleapis.com"
  disable_on_destroy = false
}
