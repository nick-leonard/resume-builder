#!/usr/bin/env ruby
# Normalize full-resume YAML files to the Resume Builder canonical schema.

require "date"
require "fileutils"
require "yaml"

ROOT_ORDER = %w[headline summary_bullets experience skills].freeze

def quoted(value)
  raise TypeError, "expected String, got #{value.class}" unless value.is_a?(String)

  escaped = value
    .gsub("\\", "\\\\")
    .gsub('"', '\\"')
    .gsub("\n", "\\n")
  "\"#{escaped}\""
end

def wrapped_lines(text, width)
  words = text.to_s.split(/\s+/)
  return [""] if words.empty?

  lines = []
  current = words.shift
  words.each do |word|
    if current.length + 1 + word.length <= width
      current << " " << word
    else
      lines << current
      current = word
    end
  end
  lines << current
end

def emit_string_list(lines, indent, key, values)
  prefix = " " * indent
  if values.empty?
    lines << "#{prefix}#{key}: []"
    return
  end

  lines << "#{prefix}#{key}:"
  values.each { |value| lines << "#{prefix}  - #{quoted(value)}" }
end

def emit_text(lines, indent, text)
  prefix = " " * indent
  lines << "#{prefix}text: >-"
  wrapped_lines(text, 88 - indent - 2).each do |line|
    lines << "#{prefix}  #{line}"
  end
end

def emit_summary_bullets(lines, bullets)
  lines << "summary_bullets:"
  bullets.each do |bullet|
    lines << "  - id: #{quoted(bullet.fetch('id'))}"
    emit_text(lines, 4, bullet.fetch("text"))
  end
end

def emit_experience(lines, entries)
  lines << "experience:"
  entries.each do |entry|
    lines << "  - company: #{quoted(entry.fetch('company'))}"
    location = entry["location"]
    lines << "    location: #{location.nil? ? 'null' : quoted(location)}"
    lines << "    positions:"

    entry.fetch("positions").each do |position|
      # Optional client engagement nested under a consulting entry. When present
      # it opens the list item, so title_lines loses the "- " marker.
      client = position["client"]
      item = "      - "
      unless client.nil?
        lines << "      - client: #{quoted(client)}"
        item = "        "
      end

      title_lines = position.fetch("title_lines")
      if title_lines.empty?
        lines << "#{item}title_lines: []"
      else
        lines << "#{item}title_lines:"
        title_lines.each { |value| lines << "          - #{quoted(value)}" }
      end
      emit_string_list(lines, 8, "dates", position.fetch("dates"))

      summary = position["summary"]
      if summary.nil?
        lines << "        summary: null"
      else
        lines << "        summary:"
        lines << "          id: #{quoted(summary.fetch('id'))}"
        emit_text(lines, 10, summary.fetch("text"))
      end

      bullets = position.fetch("bullets")
      if bullets.empty?
        lines << "        bullets: []"
      else
        lines << "        bullets:"
        bullets.each do |bullet|
          lines << "          - id: #{quoted(bullet.fetch('id'))}"
          emit_text(lines, 12, bullet.fetch("text"))
        end
      end
    end
    lines << ""
  end
  lines.pop if lines.last == ""
end

def emit_skills(lines, skills)
  lines << "skills:"
  skills.each do |category, values|
    emit_string_list(lines, 2, category, values)
  end
end

def canonical_yaml(data, source_path)
  missing = ROOT_ORDER.reject { |key| data.key?(key) }
  raise KeyError, "#{source_path}: missing root keys: #{missing.join(', ')}" unless missing.empty?

  lines = []
  if File.basename(source_path) == "resume_primary.yaml"
    lines << "# Primary resume content. Contact details and education are maintained"
    lines << "# separately in data/resume_static.yaml and merged only at render time."
    lines << ""
  elsif File.basename(source_path) == "resume_primary.template.yaml"
    lines << "# Template for primary resume content. Contact details and education belong"
    lines << "# in data/resume_static.template.yaml, not in a full-resume YAML file."
    lines << ""
  elsif File.basename(source_path).start_with?("resume_gdoc_")
    lines << "# Snapshot extracted from the source Google Doc resume."
    lines << "# Contact details and education intentionally omitted."
    lines << ""
  end

  lines << "headline: #{quoted(data.fetch('headline'))}"
  lines << ""
  emit_summary_bullets(lines, data.fetch("summary_bullets"))
  lines << ""
  emit_experience(lines, data.fetch("experience"))
  lines << ""
  emit_skills(lines, data.fetch("skills"))
  lines << ""
  lines.join("\n")
end

def load_resume(path)
  YAML.safe_load(File.read(path), permitted_classes: [Date], aliases: false)
end

mode = ARGV.shift
case mode
when "--copy"
  source = ARGV.shift or abort "missing source path"
  destination = ARGV.shift or abort "missing destination path"
  abort "unexpected arguments: #{ARGV.join(' ')}" unless ARGV.empty?
  data = load_resume(source)
  FileUtils.mkdir_p(File.dirname(destination))
  File.write(destination, canonical_yaml(data, destination))
when "--in-place"
  abort "provide at least one YAML path" if ARGV.empty?
  ARGV.each do |path|
    data = load_resume(path)
    File.write(path, canonical_yaml(data, path))
  end
else
  abort <<~USAGE
    Usage:
      ruby scripts/normalize_resume_yaml.rb --copy SOURCE DESTINATION
      ruby scripts/normalize_resume_yaml.rb --in-place FILE [FILE ...]
  USAGE
end
