use serde::Deserialize;
use shikigen_desktop_lib::backend::BackendConfig;
use std::collections::HashSet;

#[derive(Deserialize)]
struct SharedBackendConfigCases {
    schema_version: u8,
    cases: Vec<BackendConfigCase>,
}

#[derive(Deserialize)]
struct BackendConfigCase {
    case_name: String,
    document: String,
    expected_config: Option<ExpectedBackendConfig>,
}

#[derive(Deserialize)]
struct ExpectedBackendConfig {
    port: u16,
    startup_timeout_seconds: f64,
    shutdown_timeout_seconds: f64,
}

#[test]
fn backend_config_matches_shared_contract_cases() {
    let fixture: SharedBackendConfigCases = serde_json::from_str(include_str!(
        "../../../tests/fixtures/desktop_backend_config_cases.json"
    ))
    .unwrap();
    assert_eq!(fixture.schema_version, 1);
    assert!(!fixture.cases.is_empty());
    let mut case_names = HashSet::new();
    for config_case in fixture.cases {
        assert!(case_names.insert(config_case.case_name.clone()));
        let configuration_result = BackendConfig::from_document(&config_case.document);
        match config_case.expected_config {
            Some(expected_config) => {
                let backend_config = configuration_result.expect(&config_case.case_name);
                assert_eq!(
                    backend_config.start_port, expected_config.port,
                    "{}",
                    config_case.case_name
                );
                assert_eq!(
                    backend_config.startup_timeout_seconds, expected_config.startup_timeout_seconds,
                    "{}",
                    config_case.case_name
                );
                assert_eq!(
                    backend_config.shutdown_timeout_seconds,
                    expected_config.shutdown_timeout_seconds,
                    "{}",
                    config_case.case_name
                );
            }
            None => {
                let error = configuration_result.expect_err(&config_case.case_name);
                assert!(
                    !error.to_string().contains("secret-value"),
                    "{}",
                    config_case.case_name
                );
            }
        }
    }
}

#[test]
fn backend_config_allows_an_empty_host_document_and_ignores_agent_fields() {
    let defaults = BackendConfig::from_document("{}").unwrap();
    assert_eq!(defaults.start_port, 43127);
    assert_eq!(defaults.startup_timeout_seconds, 60.0);
    assert_eq!(defaults.shutdown_timeout_seconds, 10.0);
    let custom = BackendConfig::from_document(
        r#"{"model":{"key":"not read"},"backend":{"port":65535,"startup_timeout_seconds":0.5,"shutdown_timeout_seconds":2}}"#,
    ).unwrap();
    assert_eq!(custom.start_port, 65535);
    assert_eq!(custom.startup_timeout_seconds, 0.5);
    assert_eq!(custom.shutdown_timeout_seconds, 2.0);
}

#[test]
fn missing_environment_and_configuration_report_preparation_steps() {
    use shikigen_desktop_lib::backend::LaunchPlan;
    let root = std::env::temp_dir().join(format!("shikigen paths {}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(root.join("app")).unwrap();
    std::fs::write(root.join("pyproject.toml"), "").unwrap();
    std::fs::write(root.join("app/desktop.py"), "").unwrap();
    let error = LaunchPlan::from_root(&root).unwrap_err();
    assert_eq!(error.code, "environment");
    assert!(error.message.contains("uv sync"));
    std::fs::create_dir_all(root.join(".venv/Scripts")).unwrap();
    std::fs::write(root.join(".venv/Scripts/python.exe"), "").unwrap();
    assert_eq!(LaunchPlan::from_root(&root).unwrap_err().code, "config");
    std::fs::write(root.join("config.json"), r#"{"backend":{"port":45000}}"#).unwrap();
    let plan = LaunchPlan::from_root(&root).unwrap();
    std::fs::write(root.join("config.json"), r#"{"backend":{"port":45001}}"#).unwrap();
    assert_eq!(plan.config.start_port, 45000);
    assert_eq!(
        LaunchPlan::from_root(&root).unwrap().config.start_port,
        45001
    );
    assert!(plan.python.is_absolute() && plan.config_path.is_absolute());
    std::fs::remove_dir_all(root).unwrap();
}
