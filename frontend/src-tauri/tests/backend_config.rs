use shikigen_desktop_lib::backend::BackendConfig;

#[test]
fn backend_snapshot_defaults_and_strict_values() {
    let defaults = BackendConfig::from_document("{}").unwrap();
    assert_eq!(defaults.port, 43127);
    assert_eq!(defaults.startup_timeout_seconds, 60.0);
    assert_eq!(defaults.shutdown_timeout_seconds, 10.0);
    for document in [
        r#"{"backend":null}"#,
        r#"{"backend":[]}"#,
        r#"{"backend":{"extra":1}}"#,
        r#"{"backend":{"port":null}}"#,
        r#"{"backend":{"port":true}}"#,
        r#"{"backend":{"port":"43127"}}"#,
        r#"{"backend":{"port":1.0}}"#,
        r#"{"backend":{"port":0}}"#,
        r#"{"backend":{"port":65536}}"#,
        r#"{"backend":{"startup_timeout_seconds":0}}"#,
        r#"{"backend":{"shutdown_timeout_seconds":"secret-value"}}"#,
        r#"{"backend":{"shutdown_timeout_seconds":false}}"#,
        r#"{"backend":{"startup_timeout_seconds":1e400}}"#,
    ] {
        let error = BackendConfig::from_document(document).unwrap_err();
        assert!(!error.to_string().contains("secret-value"));
    }
    let custom = BackendConfig::from_document(
        r#"{"model":{"key":"not read"},"backend":{"port":65535,"startup_timeout_seconds":0.5,"shutdown_timeout_seconds":2}}"#,
    ).unwrap();
    assert_eq!(custom.port, 65535);
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
    assert_eq!(plan.config.port, 45000);
    assert_eq!(LaunchPlan::from_root(&root).unwrap().config.port, 45001);
    assert!(plan.python.is_absolute() && plan.config_path.is_absolute());
    std::fs::remove_dir_all(root).unwrap();
}
