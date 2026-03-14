# Application Load Balancer — replaces the previous API Gateway mock

# -----------------------------------------------------
# ACM Certificate (optional — only when domain is configured)
# -----------------------------------------------------

resource "aws_acm_certificate" "main" {
  count             = var.domain_name != "" ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { component = "gateway" }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in(var.domain_name != "" ? aws_acm_certificate.main[0].domain_validation_options : []) :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = var.hosted_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "main" {
  count                   = var.domain_name != "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

locals {
  certificate_arn = var.domain_name != "" ? aws_acm_certificate_validation.main[0].certificate_arn : ""
}

# -----------------------------------------------------
# Application Load Balancer
# -----------------------------------------------------

resource "aws_lb" "main" {
  name               = "${var.project}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  tags = { component = "gateway" }
}

# -----------------------------------------------------
# Target Group
# -----------------------------------------------------

resource "aws_lb_target_group" "webhook" {
  name        = "${var.project}-webhook-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = { component = "gateway" }
}

# -----------------------------------------------------
# Listeners
# -----------------------------------------------------

# HTTPS listener (443) — requires ACM certificate
resource "aws_lb_listener" "https" {
  count             = local.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.webhook.arn
  }
}

# HTTP listener — redirect to HTTPS when cert is available, otherwise forward
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.certificate_arn != "" ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = local.certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    target_group_arn = local.certificate_arn == "" ? aws_lb_target_group.webhook.arn : null
  }
}
