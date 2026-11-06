//! Policy management module — interfaces with JARVIS PolicyEngine.

use crate::modules::{ModuleHandler, result_ok, result_err, param_optional_string, param_optional_string_array};
use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::sync::{Arc, Mutex};

pub struct PolicyModule {
    grants: Arc<Mutex<HashMap<String, PolicyGrant>>>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
struct PolicyGrant {
    id: String,
    subject: String,      // agent/tool requesting
    resource: String,     // what resource (module.method)
    action: String,       // allow/deny
    conditions: Vec<String>,
    granted_at: String,
    expires_at: Option<String>,
    granted_by: String,
}

impl Default for PolicyModule {
    fn default() -> Self {
        let grants = Arc::new(Mutex::new(HashMap::new()));
        let module = Self { grants };
        
        // Load existing grants from disk
        if let Ok(content) = fs::read_to_string("/etc/jarvis-os/policy-grants.json") {
            if let Ok(loaded) = serde_json::from_str::<HashMap<String, PolicyGrant>>(&content) {
                *module.grants.lock().unwrap() = loaded;
            }
        }
        
        module
    }
}

#[async_trait]
impl ModuleHandler for PolicyModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "grant" => self.grant(params).await,
            "revoke" => self.revoke(params).await,
            "list" => self.list().await,
            "check" => self.check(params).await,
            _ => Err(format!("Unknown policy method: {}", method)),
        }
    }
}

impl PolicyModule {
    async fn grant(&self, params: &Value) -> Result<Value, String> {
        let subject = param_optional_string(params, "subject").ok_or("subject required")?;
        let resource = param_optional_string(params, "resource").ok_or("resource required")?;
        let action = param_optional_string(params, "action").unwrap_or("allow".to_string());
        let conditions = param_optional_string_array(params, "conditions").unwrap_or_default();
        let expires_at = param_optional_string(params, "expires_at");
        
        let grant_id = uuid::Uuid::new_v4().to_string();
        let grant = PolicyGrant {
            id: grant_id.clone(),
            subject,
            resource,
            action,
            conditions,
            granted_at: chrono::Utc::now().to_rfc3339(),
            expires_at,
            granted_by: "jarvis-bridge".to_string(),
        };
        
        {
            let mut grants = self.grants.lock().unwrap();
            grants.insert(grant_id.clone(), grant.clone());
        }
        
        // Persist
        Self::persist_grants(&self.grants)?;
        
        Ok(result_ok(serde_json::json!({"grant_id": grant_id, "grant": grant})))
    }

    async fn revoke(&self, params: &Value) -> Result<Value, String> {
        let grant_id = param_optional_string(params, "grant_id").ok_or("grant_id required")?;
        
        let mut grants = self.grants.lock().unwrap();
        if grants.remove(&grant_id).is_some() {
            Self::persist_grants(&self.grants)?;
            Ok(result_ok(serde_json::json!({"revoked": grant_id})))
        } else {
            Err("Grant not found".to_string())
        }
    }

    async fn list(&self) -> Result<Value, String> {
        let grants = self.grants.lock().unwrap();
        let list: Vec<PolicyGrant> = grants.values().cloned().collect();
        Ok(result_ok(serde_json::json!({"grants": list})))
    }

    async fn check(&self, params: &Value) -> Result<Value, String> {
        let subject = param_optional_string(params, "subject").ok_or("subject required")?;
        let resource = param_optional_string(params, "resource").ok_or("resource required")?;
        
        let grants = self.grants.lock().unwrap();
        let now = chrono::Utc::now();
        
        for grant in grants.values() {
            if grant.subject == subject && grant.resource == resource {
                // Check expiration
                if let Some(expires) = &grant.expires_at {
                    if let Ok(expires_dt) = chrono::DateTime::parse_from_rfc3339(expires) {
                        if now > expires_dt.with_timezone(&chrono::Utc) {
                            continue;
                        }
                    }
                }
                
                // Check conditions (simplified)
                let allowed = grant.action == "allow";
                
                return Ok(result_ok(serde_json::json!({
                    "allowed": allowed,
                    "grant_id": grant.id,
                    "conditions": grant.conditions,
                })));
            }
        }
        
        // Default deny
        Ok(result_ok(serde_json::json!({
            "allowed": false,
            "reason": "No matching grant found",
        })))
    }

    fn persist_grants(grants: &Arc<Mutex<HashMap<String, PolicyGrant>>>) -> Result<(), String> {
        let grants_map = grants.lock().unwrap();
        let content = serde_json::to_string_pretty(&*grants_map).map_err(|e| e.to_string())?;
        
        // Ensure directory exists
        if let Some(parent) = std::path::Path::new("/etc/jarvis-os/policy-grants.json").parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        
        fs::write("/etc/jarvis-os/policy-grants.json", content).map_err(|e| e.to_string())?;
        Ok(())
    }
}