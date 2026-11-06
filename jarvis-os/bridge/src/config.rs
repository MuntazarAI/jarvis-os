//! Configuration for the JARVIS-OS Bridge.
//!
//! Loaded from /etc/jarvis-os/bridge.toml by default.
//! All settings are read-only safe defaults.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

/// Top-level bridge configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Config {
    pub server: ServerConfig,
    pub modules: ModulesConfig,
    pub security: SecurityConfig,
    pub logging: LoggingConfig,
}

/// Server configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ServerConfig {
    /// Unix domain socket path
    pub socket_path: Option<PathBuf>,
    /// Maximum number of concurrent connections
    pub max_connections: Option<usize>,
    /// Connection timeout in seconds
    pub connection_timeout_secs: Option<u64>,
    /// Read timeout in seconds
    pub read_timeout_secs: Option<u64>,
}

/// Module enable/disable configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModulesConfig {
    pub system: Option<bool>,
    pub cpu: Option<bool>,
    pub memory: Option<bool>,
    pub storage: Option<bool>,
    pub network: Option<bool>,
    pub process: Option<bool>,
    pub service: Option<bool>,
    pub hardware: Option<bool>,
    pub logs: Option<bool>,
    pub policy: Option<bool>,
    pub bpf: Option<bool>,
}

/// Security configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SecurityConfig {
    /// Require PolicyEngine approval for all operations
    pub require_policy_approval: Option<bool>,
    /// Allowed Unix domain socket peer credentials (UID/GID)
    pub allowed_uids: Option<Vec<u32>>,
    /// Allowed GIDs
    pub allowed_gids: Option<Vec<u32>>,
    /// Max request size in bytes
    pub max_request_size: Option<usize>,
    /// Rate limit: max requests per second per connection
    pub rate_limit_rps: Option<f64>,
}

/// Logging configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LoggingConfig {
    pub level: Option<String>,
    pub format: Option<String>,
    pub file: Option<PathBuf>,
}

impl Config {
    /// Load configuration from a TOML file.
    /// Returns default config if file doesn't exist or is invalid.
    pub fn load(path: &std::path::Path) -> Result<Self, Box<dyn std::error::Error>> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let contents = std::fs::read_to_string(path)?;
        let config: Self = toml::from_str(&contents)?;
        Ok(config)
    }

    /// Save configuration to a TOML file.
    pub fn save(&self, path: &std::path::Path) -> Result<(), Box<dyn std::error::Error>> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let contents = toml::to_string_pretty(self)?;
        std::fs::write(path, contents)?;
        Ok(())
    }

    /// Get the effective socket path.
    pub fn socket_path(&self) -> &std::path::Path {
        self.server
            .socket_path
            .as_deref()
            .unwrap_or(std::path::Path::new("/run/jarvis-os/bridge.sock"))
    }

    /// Get the effective max connections.
    pub fn max_connections(&self) -> usize {
        self.server.max_connections.unwrap_or(100)
    }

    /// Get the effective connection timeout.
    pub fn connection_timeout(&self) -> Duration {
        Duration::from_secs(
            self.server.connection_timeout_secs.unwrap_or(30),
        )
    }

    /// Get the effective read timeout.
    pub fn read_timeout(&self) -> Duration {
        Duration::from_secs(self.server.read_timeout_secs.unwrap_or(10))
    }

    /// Check if policy approval is required.
    pub fn require_policy_approval(&self) -> bool {
        self.security.require_policy_approval.unwrap_or(true)
    }

    /// Get allowed UIDs.
    pub fn allowed_uids(&self) -> Option<&Vec<u32>> {
        self.security.allowed_uids.as_ref()
    }

    /// Get allowed GIDs.
    pub fn allowed_gids(&self) -> Option<&Vec<u32>> {
        self.security.allowed_gids.as_ref()
    }

    /// Get max request size.
    pub fn max_request_size(&self) -> usize {
        self.security.max_request_size.unwrap_or(1_048_576) // 1 MB
    }

    /// Get rate limit.
    pub fn rate_limit_rps(&self) -> f64 {
        self.security.rate_limit_rps.unwrap_or(100.0)
    }

    /// Check if a module is enabled.
    pub fn module_enabled(&self, module: &str) -> bool {
        match module {
            "system" => self.modules.system.unwrap_or(true),
            "cpu" => self.modules.cpu.unwrap_or(true),
            "memory" => self.modules.memory.unwrap_or(true),
            "storage" => self.modules.storage.unwrap_or(true),
            "network" => self.modules.network.unwrap_or(true),
            "process" => self.modules.process.unwrap_or(true),
            "service" => self.modules.service.unwrap_or(true),
            "hardware" => self.modules.hardware.unwrap_or(true),
            "logs" => self.modules.logs.unwrap_or(true),
            "policy" => self.modules.policy.unwrap_or(true),
            "bpf" => self.modules.bpf.unwrap_or(false),
            _ => false,
        }
    }

    /// Get logging level.
    pub fn log_level(&self) -> &str {
        self.logging.level.as_deref().unwrap_or("info")
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: ServerConfig::default(),
            modules: ModulesConfig::default(),
            security: SecurityConfig::default(),
            logging: LoggingConfig::default(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = Config::default();
        assert_eq!(config.socket_path(), std::path::Path::new("/run/jarvis-os/bridge.sock"));
        assert_eq!(config.max_connections(), 100);
        assert!(config.require_policy_approval());
    }

    #[test]
    fn test_module_enabled_default() {
        let config = Config::default();
        assert!(config.module_enabled("system"));
        assert!(config.module_enabled("cpu"));
        assert!(config.module_enabled("network"));
        assert!(!config.module_enabled("nonexistent"));
    }

    #[test]
    fn test_save_and_load(tmp_path: std::path::PathBuf) {
        let path = tmp_path.join("test_config.toml");
        let config = Config {
            server: ServerConfig {
                max_connections: Some(50),
                ..Default::default()
            },
            ..Default::default()
        };
        config.save(&path).unwrap();
        let loaded = Config::load(&path).unwrap();
        assert_eq!(loaded.max_connections(), 50);
    }
}