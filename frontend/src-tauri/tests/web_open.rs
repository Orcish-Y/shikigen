use shikigen_desktop_lib::web_open::open_web_url;

#[test]
fn only_explicit_http_and_https_reach_the_system_browser() {
    for raw in ["HTTPS://example.org/path?q=a#b", "http://localhost:1234/a"] {
        let mut opened = None;
        assert!(open_web_url(raw, |url| {
            opened = Some(url.to_owned());
            Ok(())
        })
        .is_ok());
        assert!(opened.unwrap().starts_with("http"));
    }
    for raw in [
        "file:///C:/secret.txt",
        "mailto:me@example.org",
        "javascript:alert(1)",
        "data:text/html,hi",
        "//example.org",
        "http:example.org",
        "https://",
        "https://example.org\n",
        "https://example.org\\evil",
    ] {
        let failure =
            open_web_url(raw, |_| panic!("invalid references cannot reach opener")).unwrap_err();
        assert_eq!(failure.code, "invalid_web_url");
    }
}

#[test]
fn system_open_failure_is_returned_without_claiming_acceptance() {
    let failure = open_web_url("https://example.org", |_| Err("系统拒绝打开".into())).unwrap_err();
    assert_eq!(failure.code, "web_open_failed");
    assert_eq!(failure.message, "系统拒绝打开");
}
