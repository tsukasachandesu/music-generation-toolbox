from setuptools import setup, find_namespace_packages

setup(name='music-generation-toolbox',
      version='0.2.0',
      description='Toolbox for generating music',
      author='Vincent Bons',
      url='https://github.com/wingedsheep/music-generation-toolbox',
      download_url='https://github.com/wingedsheep/music-generation-toolbox',
      license='MIT',
      install_requires=['pretty_midi>=0.2.9', 'miditoolkit>=0.1.15', 'scipy>=1.7.1',
                        'pylab-sdk>=1.3.2', 'requests>=2.26.0', 'matplotlib>=3.4.3',
                        'reformer-pytorch>=1.4.3', 'x-transformers>=0.20.2', 'torch~=1.10.1',
                        'numpy~=1.21.3', 'routing_transformer>=1.6.0'],
      packages=find_namespace_packages(),
      package_data={"": ["*.mid", "*.midi"]})
