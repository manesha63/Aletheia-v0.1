import { validateMessage, sanitizeInput } from '../validation';

describe('validation utils', () => {
  describe('validateMessage', () => {
    it('should return valid result for valid messages', () => {
      expect(validateMessage('Hello, this is a valid message').isValid).toBe(true);
      expect(validateMessage('A').isValid).toBe(true); // Single character
      expect(validateMessage('A'.repeat(10000)).isValid).toBe(true); // Max length
    });

    it('should return invalid result for invalid messages', () => {
      expect(validateMessage('').isValid).toBe(false);
      expect(validateMessage('   ').isValid).toBe(false); // Only whitespace
      expect(validateMessage('A'.repeat(10001)).isValid).toBe(false); // Exceeds max length
    });

    it('should trim whitespace before validation', () => {
      expect(validateMessage('  valid message  ').isValid).toBe(true);
      expect(validateMessage('  \n\t  ').isValid).toBe(false);
    });
    
    it('should provide error messages for invalid inputs', () => {
      const emptyResult = validateMessage('');
      expect(emptyResult.error).toBe('Message cannot be empty');
      
      const tooLongResult = validateMessage('A'.repeat(10001));
      expect(tooLongResult.error).toContain('Message too long');
    });
    
    it('should sanitize dangerous content', () => {
      const result = validateMessage('Hello<script>alert("XSS")</script>World');
      expect(result.isValid).toBe(true);
      expect(result.sanitized).toBe('HelloWorld');
    });
  });

  describe('sanitizeInput', () => {
    it('should remove dangerous HTML tags', () => {
      expect(sanitizeInput('<script>alert("XSS")</script>Hello')).toBe('Hello');
      expect(sanitizeInput('Hello<script>evil()</script>World')).toBe('HelloWorld');
      expect(sanitizeInput('<iframe src="evil.com"></iframe>')).toBe('');
    });

    it('should preserve safe HTML tags', () => {
      expect(sanitizeInput('<b>Bold</b> text')).toBe('<b>Bold</b> text');
      expect(sanitizeInput('<i>Italic</i> and <em>emphasis</em>')).toBe('<i>Italic</i> and <em>emphasis</em>');
      expect(sanitizeInput('<a href="https://example.com">Link</a>')).toBe('<a href="https://example.com">Link</a>');
    });

    it('should remove event handlers', () => {
      expect(sanitizeInput('<div onclick="alert(1)">Click me</div>')).toBe('<div>Click me</div>');
      expect(sanitizeInput('<img src="x" onerror="alert(1)">')).toBe('<img src="x">');
    });

    it('should handle markdown-style content', () => {
      const markdown = '# Title\n\n**Bold** and *italic* text';
      expect(sanitizeInput(markdown)).toBe(markdown);
    });

    it('should handle empty and null inputs', () => {
      expect(sanitizeInput('')).toBe('');
      expect(sanitizeInput(null)).toBe('');
      expect(sanitizeInput(undefined)).toBe('');
    });

    it('should handle complex nested HTML', () => {
      const input = '<div><p>Safe <script>alert(1)</script> content</p></div>';
      const expected = '<div><p>Safe  content</p></div>';
      expect(sanitizeInput(input)).toBe(expected);
    });
  });
});