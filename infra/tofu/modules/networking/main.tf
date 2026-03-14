# VPC, subnets, NAT gateway, security groups, and VPC endpoints

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

# -----------------------------------------------------
# VPC
# -----------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name      = "${var.project}-vpc"
    component = "networking"
  }
}

# -----------------------------------------------------
# Subnets
# -----------------------------------------------------

resource "aws_subnet" "public" {
  count                   = length(local.azs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name      = "${var.project}-public-${local.azs[count.index]}"
    component = "networking"
  }
}

resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = {
    Name      = "${var.project}-private-${local.azs[count.index]}"
    component = "networking"
  }
}

# -----------------------------------------------------
# Internet Gateway
# -----------------------------------------------------

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name      = "${var.project}-igw"
    component = "networking"
  }
}

# -----------------------------------------------------
# NAT Gateway (1 for staging, 2 for production)
# -----------------------------------------------------

resource "aws_eip" "nat" {
  count  = var.environment == "production" ? 2 : 1
  domain = "vpc"

  tags = {
    Name      = "${var.project}-nat-eip-${count.index}"
    component = "networking"
  }
}

resource "aws_nat_gateway" "main" {
  count         = var.environment == "production" ? 2 : 1
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name      = "${var.project}-nat-${count.index}"
    component = "networking"
  }

  depends_on = [aws_internet_gateway.main]
}

# -----------------------------------------------------
# Route Tables
# -----------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name      = "${var.project}-public-rt"
    component = "networking"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = length(local.azs)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[min(count.index, length(aws_nat_gateway.main) - 1)].id
  }

  tags = {
    Name      = "${var.project}-private-rt-${count.index}"
    component = "networking"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# -----------------------------------------------------
# Security Groups
# -----------------------------------------------------

resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-alb-"
  description = "ALB security group — HTTPS inbound"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP (redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name      = "${var.project}-alb-sg"
    component = "networking"
  }
}

resource "aws_security_group" "webhook_ecs" {
  name_prefix = "${var.project}-webhook-ecs-"
  description = "Webhook ECS tasks — port 8000 from ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "FastAPI from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name      = "${var.project}-webhook-ecs-sg"
    component = "networking"
  }
}

resource "aws_security_group" "worker_ecs" {
  name_prefix = "${var.project}-worker-ecs-"
  description = "Worker ECS tasks — egress only"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name      = "${var.project}-worker-ecs-sg"
    component = "networking"
  }
}

# -----------------------------------------------------
# VPC Endpoints
# -----------------------------------------------------

# DynamoDB gateway endpoint (free)
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = {
    Name      = "${var.project}-dynamodb-vpce"
    component = "networking"
  }
}

# Interface endpoints — Bedrock always, others only in production
resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-bedrock-vpce"
    component = "networking"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  count               = var.environment == "production" ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-ecr-api-vpce"
    component = "networking"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count               = var.environment == "production" ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-ecr-dkr-vpce"
    component = "networking"
  }
}

resource "aws_vpc_endpoint" "secretsmanager" {
  count               = var.environment == "production" ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-secretsmanager-vpce"
    component = "networking"
  }
}

resource "aws_vpc_endpoint" "logs" {
  count               = var.environment == "production" ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-logs-vpce"
    component = "networking"
  }
}

resource "aws_vpc_endpoint" "sqs" {
  count               = var.environment == "production" ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name      = "${var.project}-sqs-vpce"
    component = "networking"
  }
}

# Security group for VPC interface endpoints
resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.project}-vpce-"
  description = "VPC endpoint interface security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name      = "${var.project}-vpce-sg"
    component = "networking"
  }
}
