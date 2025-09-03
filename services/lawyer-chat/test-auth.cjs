const bcrypt = require('bcryptjs');

// Hashes from database
const demoHash = '$2a$12$/H5nSVmw7n/0MR2ymCXLiOKJcvZVRHcVZYXjGvK5qBe8JqIJAj5ey';
const adminHash = '$2a$12$GpJRXfLZzZW7T9fKZKnkVuW9C6aGXqJT9RqY0P8pVJvWQQIqvLg76';

async function testPasswords() {
    console.log('Testing with bcryptjs compare (same as lawyer-chat uses):');
    
    const demoResult = await bcrypt.compare('demo123', demoHash);
    console.log('demo@reichmanjorgensen.com with "demo123":', demoResult);
    
    const adminResult = await bcrypt.compare('admin123', adminHash);
    console.log('admin@reichmanjorgensen.com with "admin123":', adminResult);
}

testPasswords();
