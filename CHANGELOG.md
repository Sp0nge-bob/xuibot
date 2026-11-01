# Changelog

All notable changes to the `vpn-platega-bot` project will be documented in this file.

## [1.5.0] - 2026-11-01

### Security Hardening & Lifecycle Integrity Release

#### Added
- **Durable Payment Inbox (`payment_inbox`, `payment_states`)**: Persistent transactional queue storing incoming Platega webhook callbacks with leased worker state transitions. Prevents lost payments during worker restart or network downtime.
- **Queue Saturation Retry (HTTP 503)**: When the asynchronous fulfillment queue reaches capacity, the service returns an explicit retryable 503 Service Unavailable, signalling the payment gateway to retry.
- **Atomic Concurrency Protection (CAS)**: Implemented Compare-And-Swap retry loop for `extend_subscription_record` and `add_subscription_bonus_days` (`CROSS-002`), eliminating Lost Update race conditions during concurrent renewals across bot and website.
- **Fail-Closed Secret Validation**: Mandatory startup verification for `SECRET_KEY` (minimum 32 bytes) preventing execution with default or weak cryptographic seeds.
- **Credential Redaction in Logs**: Fully sanitized sensitive Redis connection URLs in FSM storage logs and redacted bearer tokens/subscription URLs in 3x-ui service diagnostics.

#### Changed
- **Platega Webhook Verification**: Timing-safe HMAC (`hmac.compare_digest`) verification executed strictly prior to rate-limiting budget increments and JSON body parsing.
- **Amount & Currency Validation**: Strict fail-closed verification of payment amounts with tolerance limited to gateway processing fees (maximum +25%), rejecting underpayments.
- **Shared Database Schema Alignment**: Harmonized SQLite tables with `vpnwebsite` without blocking foreign key constraints on `orders.id`.
- **Identity Linking Transaction**: Telegram-to-email identity linking executed in a single atomic transaction with conflict detection and isolation.

---

## [1.4.1] - 2026-11-01

### Pre-Audit Baseline Snapshot
- Snapshot release capturing the baseline state before security audit fixes (`4960c9f`).
- Fix trial limit IP default configuration to prevent CDN IP bans.
- Neutralize email linking compliance notices.
