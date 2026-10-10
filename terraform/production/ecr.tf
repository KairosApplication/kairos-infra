resource "aws_ecr_repository" "api" {
  for_each             = var.services
  name                 = "kairos/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration {
    encryption_type = "AES256"
  }
  image_scanning_configuration {
    scan_on_push = true
  }
}

# Tagged releases are retained so a rollback can always use an older digest.
resource "aws_ecr_lifecycle_policy" "api" {
  for_each   = var.services
  repository = aws_ecr_repository.api[each.key].name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire only untagged build layers after 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    }]
  })
}
