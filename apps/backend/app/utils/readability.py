from readabilipy import simple_json_from_html_string
from markdownify import markdownify as md

class Article:
  def __init__(self, title = '', html_content = ''):
     self.title = title
     self.html_content = html_content
     pass

  def to_markdown(self, including_title: bool = True) -> str:
    markdown = ""
    if including_title:
        markdown += f"# {self.title}\n\n"

    if self.html_content is None or not str(self.html_content).strip():
        markdown += "*No content available*\n"
    else:
        markdown += md(self.html_content)

    return markdown

class HtmlReadabilityExtractor:
  def extract_article(self, html: str):
    try:
      article = simple_json_from_html_string(html, use_readability=True)

    except Exception as e:
      print(e)
      article = simple_json_from_html_string(html, use_readability=False)

    html_content = article.get("content")
    if not html_content or not str(html_content).strip():
        html_content = "No content could be extracted from this page"

    title = article.get("title")
    if not title or not str(title).strip():
        title = "Untitled"

    return Article(title, html_content)