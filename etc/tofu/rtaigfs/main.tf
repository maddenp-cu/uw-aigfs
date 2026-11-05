terraform {
  backend "gcs" {
    bucket = "oar-gsl-hpc-aw-0103-state"
    prefix = "rtaigfs"
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

resource "google_compute_network" "network" {
  name = "rtaigfs-net"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name = "rtaigfs-subnet"
  ip_cidr_range = "192.168.1.0/24"
  network = google_compute_network.network.id
  region = "us-central1"
}

resource "google_compute_instance" "instance" {
  name = "rtaigfs-instance"
  machine_type = "e2-standard-2"
  zone = "us-central1-c"
  tags = ["iap-ssh", "nfs-server"]
  metadata_startup_script = file("${path.module}/provision-rtaigfs-instance.sh")
  metadata = {
    "rtaigfs-user-yaml" = file("${path.module}/user.yaml")
  }
  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-13"
      size = 50
    }
  }
  network_interface {
    network = google_compute_network.network.id
    subnetwork = google_compute_subnetwork.subnet.id
  }
  shielded_instance_config {
    enable_secure_boot = true
  }
}

resource "google_compute_router" "router" {
  name = "rtaigfs-router"
  network = google_compute_network.network.id
  region = "us-central1"
}

resource "google_compute_router_nat" "nat" {
  name = "rtaigfs-nat"
  router = google_compute_router.router.name
  region = "us-central1"
  nat_ip_allocate_option = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_firewall" "firewall_rule" {
  name = "rtaigfs-allow-iap-ssh"
  network = google_compute_network.network.id
  direction = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags = ["iap-ssh"]
  allow {
    protocol = "tcp"
    ports = ["22"]
  }
}

resource "google_compute_firewall" "nfs" {
  name = "rtaigfs-allow-nfs"
  network = google_compute_network.network.id
  direction = "INGRESS"
  source_ranges = ["192.168.1.0/24"]
  target_tags = ["nfs-server"]
  allow {
    protocol = "tcp"
    ports = ["2049"]
  }
}
