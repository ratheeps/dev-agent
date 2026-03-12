output "api_id" {
  value = aws_api_gateway_rest_api.webhook.id
}

output "api_url" {
  value = aws_api_gateway_stage.prod.invoke_url
}

output "webhook_endpoint" {
  value = "${aws_api_gateway_stage.prod.invoke_url}/webhook"
}
