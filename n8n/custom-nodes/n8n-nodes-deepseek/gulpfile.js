const path = require('path');
const { task, src, dest } = require('gulp');

task('build:icons', copyIcons);

function copyIcons(done) {
	const nodeSource = path.resolve('nodes', '**', '*.{png,svg}');
	const nodeDestination = path.resolve('dist', 'nodes');

	src(nodeSource).pipe(dest(nodeDestination));

	// Only copy credentials icons if credentials directory exists and has files
	const fs = require('fs');
	const credDir = path.resolve('credentials');
	if (fs.existsSync(credDir)) {
		const credSource = path.resolve('credentials', '**', '*.{png,svg}');
		const credDestination = path.resolve('dist', 'credentials');
		return src(credSource).pipe(dest(credDestination));
	}

	// Signal completion if no credentials directory
	done();
}
