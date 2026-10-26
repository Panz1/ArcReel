{% for point in hook_points %}
- 第 {{ point.index }} 条〔{{ point.kind }}〕{{ point.description }}{% if point.characters %}（涉及：{{ point.characters | join("、") }}）{% endif %}｜原文：{{ point.anchor }}
{% endfor %}
