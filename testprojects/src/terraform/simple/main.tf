
resource "random_uuid" "default" {
}

output "uuid" {
  value = random_uuid.default.result
}

