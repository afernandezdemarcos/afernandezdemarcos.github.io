-- Pandoc filter applied to every page (see build.py).

-- Links that point outside the page's folder structure are left alone;
-- relative ones are rewritten because foo.tex is published as foo/index.html.
local function is_relative(url)
  return url ~= "" and not (url:match("^%a[%w+.-]*:") or url:match("^/") or url:match("^#"))
end

function Pandoc(doc)
  local prefix = doc.meta.rel_prefix and pandoc.utils.stringify(doc.meta.rel_prefix) or ""
  local figures = 0

  return doc:walk {
    Link = function(el)
      -- \ref / \eqref that pandoc could not resolve (equations): let MathJax do it
      local kind, label = el.attributes["reference-type"], el.attributes["reference"]
      if kind and pandoc.utils.stringify(el.content) == "[" .. label .. "]" then
        local cmd = kind == "eqref" and "\\eqref" or "\\ref"
        return pandoc.RawInline("html", "\\(" .. cmd .. "{" .. label .. "}\\)")
      end
      -- External links and PDFs open in a new tab
      if el.target:match("^https?://") or el.target:lower():match("%.pdf$") then
        el.attributes.target = "_blank"
        el.attributes.rel = "noopener"
      end
      if is_relative(el.target) then
        el.target = prefix .. el.target
      end
      return el
    end,

    Image = function(el)
      if is_relative(el.src) then
        el.src = prefix .. el.src
      end
      return el
    end,

    -- Number captioned figures ("Figure 1."), matching pandoc's \ref numbers
    Figure = function(el)
      if #el.caption.long == 0 then
        return nil
      end
      figures = figures + 1
      local first = el.caption.long[1]
      if first.content then
        first.content:insert(1, pandoc.Space())
        first.content:insert(1, pandoc.Strong { pandoc.Str("Figure " .. figures .. ".") })
      end
      return el
    end,
  }
end
